PYTHON ?= .venv/bin/python
RUFF ?= .venv/bin/ruff
COMPOSE ?= docker compose
SELFHOST_ENV ?= .env.selfhost
SELFHOST_COMPOSE ?= $(COMPOSE) --env-file $(SELFHOST_ENV) -f docker-compose.selfhost.yml
INFINITY_CONTEXT_PYTHONPATH ?= packages/infinity_context_core:packages/infinity_context_server:packages/infinity_context_adapters:packages/infinity_context_sdk:packages/infinity_context_obsidian:packages/infinity_context_mcp:packages/infinity_context_cli
export PYTHONPATH := $(INFINITY_CONTEXT_PYTHONPATH)$(if $(PYTHONPATH),:$(PYTHONPATH))
FRONTEND_DIR ?= frontend
FLUTTER ?= $(shell command -v flutter 2>/dev/null || if [ -x "$$HOME/dev/flutter/bin/flutter" ]; then echo "$$HOME/dev/flutter/bin/flutter"; elif [ -x "$$HOME/dev/projects/flutter/bin/flutter" ]; then echo "$$HOME/dev/projects/flutter/bin/flutter"; else echo flutter; fi)
MEMORY_FRONTEND_MARIONETTE_REPORT ?= .e2e-artifacts/frontend-marionette-local-e2e.json
MEMORY_SERVER_ENV ?= MEMORY_AUTO_CREATE_SCHEMA=true MEMORY_SERVICE_TOKEN=local-dev-token
PLUGIN_KIT_AI ?= scripts/plugin-kit-ai-local
MEMORY_AGENT_PLUGIN_ROOT ?= plugins/infinity-context-agent-plugin
MEMORY_AGENT_CURSOR_WORKSPACE_PLUGIN_ROOT ?= plugins/infinity-context-agent-plugin-cursor-workspace
MEMORY_AGENT_GEMINI_HOOK_PLUGIN_ROOT ?= plugins/infinity-context-agent-plugin-gemini-hooks
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
OBSIDIAN_PLUGIN_DIR ?= packages/infinity_context_obsidian_plugin

.PHONY: infinity-context-format
infinity-context-format:
	$(RUFF) format .

.PHONY: infinity-context-lint
infinity-context-lint:
	$(RUFF) check .

.PHONY: infinity-context-test-unit
infinity-context-test-unit:
	$(PYTHON) -m pytest tests/unit

.PHONY: infinity-context-test-all
infinity-context-test-all:
	$(PYTHON) -m pytest

.PHONY: infinity-context-test-application
infinity-context-test-application:
	$(PYTHON) -m pytest tests/unit/test_domain_fact.py tests/unit/test_facts_api.py tests/unit/test_legacy_and_context_api.py tests/unit/test_suggestions_api.py

.PHONY: infinity-context-test-integration
infinity-context-test-integration:
	$(PYTHON) -m pytest tests/unit/test_provider_adapters.py tests/unit/test_worker_eval.py

.PHONY: infinity-context-test-e2e
infinity-context-test-e2e:
	$(PYTHON) -m pytest tests/e2e

.PHONY: infinity-context-multimodal-production-e2e
infinity-context-multimodal-production-e2e:
	$(PYTHON) -m pytest tests/e2e/test_multimodal_production_acceptance_e2e.py tests/e2e/test_multimodal_ingestion_edge_cases_e2e.py -q

.PHONY: infinity-context-multimodal-live-provider-canary
infinity-context-multimodal-live-provider-canary:
	$(PYTHON) scripts/multimodal_live_provider_canary.py

.PHONY: infinity-context-multimodal-provider-contract-canary
infinity-context-multimodal-provider-contract-canary:
	$(PYTHON) scripts/multimodal_live_provider_canary.py --allow-missing-key --skip-invalid-key-probe

.PHONY: infinity-context-multimodal-docker-live-proof
infinity-context-multimodal-docker-live-proof:
	$(PYTHON) scripts/multimodal_docker_live_proof.py

.PHONY: infinity-context-multimodal-production-goal-audit
infinity-context-multimodal-production-goal-audit:
	$(PYTHON) scripts/multimodal_production_goal_audit.py

.PHONY: infinity-context-frontend-pub-get
infinity-context-frontend-pub-get:
	cd $(FRONTEND_DIR) && $(FLUTTER) pub get

.PHONY: infinity-context-frontend-analyze
infinity-context-frontend-analyze:
	cd $(FRONTEND_DIR) && $(FLUTTER) analyze

.PHONY: infinity-context-frontend-test
infinity-context-frontend-test:
	cd $(FRONTEND_DIR) && $(FLUTTER) test

.PHONY: infinity-context-frontend-build-macos
infinity-context-frontend-build-macos:
	cd $(FRONTEND_DIR) && $(FLUTTER) build macos --debug

.PHONY: infinity-context-frontend-check
infinity-context-frontend-check: infinity-context-frontend-analyze infinity-context-frontend-test

.PHONY: infinity-context-frontend-marionette-memory-e2e
infinity-context-frontend-marionette-memory-e2e: infinity-context-up-lite
	for i in $$(seq 1 90); do curl -fsS http://127.0.0.1:7788/v1/health >/dev/null && break; if [ $$i -eq 90 ]; then $(COMPOSE) logs --tail=120 infinity_context_server; exit 1; fi; sleep 1; done
	cd $(FRONTEND_DIR) && $(FLUTTER) pub get --enforce-lockfile && dart_bin="$$(dirname "$(FLUTTER)")/dart"; if [ ! -x "$$dart_bin" ]; then dart_bin=dart; fi; FLUTTER_BIN="$(FLUTTER)" INFINITY_CONTEXT_BACKEND_HOST=127.0.0.1 INFINITY_CONTEXT_BACKEND_PORT=7788 INFINITY_CONTEXT_SERVICE_TOKEN=local-dev-token INFINITY_CONTEXT_SPACE_SLUG=marionette-anchor-e2e "$$dart_bin" run tool/marionette_anchor_lifecycle_e2e.dart

.PHONY: infinity-context-frontend-marionette-local-e2e
infinity-context-frontend-marionette-local-e2e:
	$(PYTHON) scripts/frontend_marionette_local_e2e.py --python "$(PYTHON)" --flutter "$(FLUTTER)" --frontend-dir "$(FRONTEND_DIR)" --report-out "$(MEMORY_FRONTEND_MARIONETTE_REPORT)"

.PHONY: infinity-context-frontend-marionette-anchor-e2e
infinity-context-frontend-marionette-anchor-e2e: infinity-context-frontend-marionette-memory-e2e

.PHONY: infinity-context-desktop-confidence
infinity-context-desktop-confidence:
	@set -e; \
	cleanup() { $(MAKE) infinity-context-down >/dev/null || true; }; \
	trap cleanup EXIT INT TERM; \
	$(MAKE) infinity-context-test-quality; \
	$(MAKE) infinity-context-frontend-check; \
	$(MAKE) infinity-context-frontend-marionette-memory-e2e; \
	git diff --check; \
	$(MAKE) infinity-context-secret-scan

.PHONY: infinity-context-scale-chaos-load-e2e
infinity-context-scale-chaos-load-e2e:
	$(PYTHON) -m pytest tests/e2e/test_memory_scale_chaos_load_e2e.py -q

.PHONY: infinity-context-obsidian-python-test
infinity-context-obsidian-python-test:
	$(PYTHON) -m pytest tests/unit/test_obsidian_note_format.py tests/unit/test_obsidian_sync.py tests/unit/test_obsidian_cli.py tests/unit/test_mcp_obsidian_prepare.py tests/unit/test_mcp_obsidian_tools.py tests/unit/test_mcp_adapter.py tests/e2e/test_obsidian_cli_e2e.py -q

.PHONY: infinity-context-obsidian-live-smoke
infinity-context-obsidian-live-smoke:
	$(PYTHON) scripts/obsidian_connector_live_smoke.py
	$(PYTHON) scripts/obsidian_mcp_smoke.py

.PHONY: infinity-context-obsidian-plugin-check
infinity-context-obsidian-plugin-check:
	cd $(OBSIDIAN_PLUGIN_DIR) && npm run typecheck
	cd $(OBSIDIAN_PLUGIN_DIR) && npm run build

.PHONY: infinity-context-obsidian-test
infinity-context-obsidian-test: infinity-context-obsidian-python-test infinity-context-obsidian-live-smoke infinity-context-obsidian-plugin-check

.PHONY: infinity-context-obsidian-ui-e2e
infinity-context-obsidian-ui-e2e:
	cd $(OBSIDIAN_PLUGIN_DIR) && INFINITY_CONTEXT_RUN_OBSIDIAN_E2E=1 npm run test:e2e:obsidian

.PHONY: infinity-context-eval
infinity-context-eval:
	$(PYTHON) -m infinity_context_server eval run --suite small-golden
	$(PYTHON) -m infinity_context_server eval run --suite quality-golden
	$(PYTHON) -m infinity_context_server eval run --suite semantic-linking-golden
	$(PYTHON) -m infinity_context_server eval run --suite long-memory-golden
	$(PYTHON) -m infinity_context_server eval run --suite auto-memory-golden
	$(PYTHON) -m infinity_context_server eval run --suite graph-native-golden
	$(PYTHON) -m infinity_context_server eval snapshots --suite prompt-contract

.PHONY: infinity-context-quality-scorecard
infinity-context-quality-scorecard:
	$(PYTHON) -m infinity_context_server eval scorecard --report-out .e2e-artifacts/memory-quality-scorecard.json

.PHONY: infinity-context-quality-scorecard-from-reports
infinity-context-quality-scorecard-from-reports:
	@test -n "$${MEMORY_SCORECARD_SUITE_REPORTS:-}" || (echo "Set MEMORY_SCORECARD_SUITE_REPORTS to one or more eval report paths."; exit 1)
	$(PYTHON) -m infinity_context_server eval scorecard $$(printf ' --suite-report %s' $${MEMORY_SCORECARD_SUITE_REPORTS})

.PHONY: infinity-context-quality-scorecard-top-evidence
infinity-context-quality-scorecard-top-evidence:
	@test -n "$${MEMORY_SCORECARD_SUITE_REPORTS:-}" || (echo "Set MEMORY_SCORECARD_SUITE_REPORTS to deterministic eval, full-provider canary, agent behavior and public benchmark report paths."; exit 1)
	$(PYTHON) -m infinity_context_server eval scorecard --require-top-evidence $$(printf ' --suite-report %s' $${MEMORY_SCORECARD_SUITE_REPORTS})

.PHONY: infinity-context-quality-evidence-bundle
infinity-context-quality-evidence-bundle:
	@set -e; \
	set -- --output-dir "$${MEMORY_QUALITY_EVIDENCE_DIR:-.tmp/infinity-context-quality-evidence}"; \
	if [ "$${MEMORY_QUALITY_EVIDENCE_REQUIRE_TOP:-false}" = "true" ]; then set -- "$$@" --require-top-evidence; fi; \
	for report in $${MEMORY_SCORECARD_EXTRA_REPORTS:-}; do set -- "$$@" --extra-report "$$report"; done; \
	$(PYTHON) scripts/quality_evidence_bundle.py "$$@"

.PHONY: infinity-context-top-evidence-preflight
infinity-context-top-evidence-preflight:
	@$(PYTHON) -m infinity_context_server.top_evidence_preflight --json

.PHONY: infinity-context-top-evidence-bundle
infinity-context-top-evidence-bundle:
	@set -e; \
	export MEMORY_MULTIMODAL_PROVIDER_PROBE_INVALID_KEY="$${MEMORY_MULTIMODAL_PROVIDER_PROBE_INVALID_KEY:-1}"; \
	$(PYTHON) -m infinity_context_server.top_evidence_preflight --json; \
	evidence_dir="$${MEMORY_QUALITY_EVIDENCE_DIR:-.tmp/infinity-context-top-evidence}"; \
	external_report="$$evidence_dir/full-provider-agent-public.json"; \
	multimodal_report="$$evidence_dir/multimodal-live-provider.json"; \
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
	export MEMORY_PUBLIC_BENCHMARK_MIN_ACCURACY="$${MEMORY_PUBLIC_BENCHMARK_MIN_ACCURACY:-0.947}"; \
	export MEMORY_PUBLIC_BENCHMARK_COMPETITIVE_FLOOR="$${MEMORY_PUBLIC_BENCHMARK_COMPETITIVE_FLOOR:-true}"; \
	export MEMORY_OPENAI_API_KEY="$${MEMORY_OPENAI_API_KEY:-$${OPENAI_API_KEY:-$${MEMORY_AGENT_BENCH_OPENAI_API_KEY}}}"; \
	export OPENAI_API_KEY="$${OPENAI_API_KEY:-$${MEMORY_OPENAI_API_KEY:-$${MEMORY_AGENT_BENCH_OPENAI_API_KEY}}}"; \
	export MEMORY_MULTIMODAL_PROVIDER_CANARY_REPORT_OUT="$$multimodal_report"; \
	$(PYTHON) scripts/multimodal_live_provider_canary.py; \
	$(PYTHON) scripts/clean_full_smoke.py; \
	$(PYTHON) scripts/quality_evidence_bundle.py \
		--output-dir "$$evidence_dir" \
		--extra-report "$$external_report" \
		--extra-report "$$multimodal_report" \
		--expected-git-commit "$$expected_git_commit" \
		$$allow_dirty_arg \
		--require-top-evidence

.PHONY: infinity-context-public-benchmark
infinity-context-public-benchmark:
	@test -n "$${MEMORY_PUBLIC_BENCHMARK_DATASET:-}" || (echo "Set MEMORY_PUBLIC_BENCHMARK_DATASET to a LoCoMo/LongMemEval-like JSON or JSONL file."; exit 1)
	@set -e; \
	set -- --dataset "$${MEMORY_PUBLIC_BENCHMARK_DATASET}"; \
	if [ -n "$${MEMORY_PUBLIC_BENCHMARK_REPORT_OUT:-}" ]; then set -- "$$@" --report-out "$${MEMORY_PUBLIC_BENCHMARK_REPORT_OUT}"; fi; \
	if [ -n "$${MEMORY_PUBLIC_BENCHMARK_API_URL:-}" ]; then set -- "$$@" --api-url "$${MEMORY_PUBLIC_BENCHMARK_API_URL}"; fi; \
	if [ -n "$${MEMORY_PUBLIC_BENCHMARK_NAME:-}" ]; then set -- "$$@" --benchmark "$${MEMORY_PUBLIC_BENCHMARK_NAME}"; fi; \
	if [ -n "$${MEMORY_PUBLIC_BENCHMARK_MIN_ACCURACY:-}" ]; then set -- "$$@" --min-accuracy "$${MEMORY_PUBLIC_BENCHMARK_MIN_ACCURACY}"; fi; \
	if [ -n "$${MEMORY_PUBLIC_BENCHMARK_MAX_CASES:-}" ]; then set -- "$$@" --max-cases "$${MEMORY_PUBLIC_BENCHMARK_MAX_CASES}"; fi; \
	$(PYTHON) -m infinity_context_server eval public-benchmark "$$@"

.PHONY: infinity-context-memora-direct-smoke
infinity-context-memora-direct-smoke:
	@$(PYTHON) scripts/memora_direct_mcp_smoke.py --report-out "$(MEMORA_DIRECT_SMOKE_REPORT)"

.PHONY: infinity-context-compare-memora
infinity-context-compare-memora:
	@set -e; \
	smoke_report="$${MEMORA_DIRECT_SMOKE_REPORT:-$(MEMORA_DIRECT_SMOKE_REPORT)}"; \
	if [ -n "$$smoke_report" ] && [ -f "$$smoke_report" ]; then \
		$(PYTHON) -m infinity_context_server.memora_comparison --memora-smoke-report "$$smoke_report"; \
	else \
		$(PYTHON) -m infinity_context_server.memora_comparison; \
	fi

.PHONY: infinity-context-official-public-benchmark-canary
infinity-context-official-public-benchmark-canary:
	@set -e; \
	set --; \
	if [ -n "$${MEMORY_PUBLIC_BENCHMARK_NAME:-}" ]; then set -- "$$@" --benchmark "$${MEMORY_PUBLIC_BENCHMARK_NAME}"; fi; \
	if [ -n "$${MEMORY_PUBLIC_BENCHMARK_MAX_CASES:-}" ]; then set -- "$$@" --max-cases "$${MEMORY_PUBLIC_BENCHMARK_MAX_CASES}"; fi; \
	if [ -n "$${MEMORY_PUBLIC_BENCHMARK_MIN_ACCURACY:-}" ]; then set -- "$$@" --min-accuracy "$${MEMORY_PUBLIC_BENCHMARK_MIN_ACCURACY}"; fi; \
	if [ -n "$${MEMORY_PUBLIC_BENCHMARK_API_URL:-}" ]; then set -- "$$@" --api-url "$${MEMORY_PUBLIC_BENCHMARK_API_URL}"; fi; \
	if [ -n "$${MEMORY_PUBLIC_BENCHMARK_AUTH_TOKEN:-}" ]; then set -- "$$@" --auth-token "$${MEMORY_PUBLIC_BENCHMARK_AUTH_TOKEN}"; fi; \
	if [ -n "$${MEMORY_PUBLIC_BENCHMARK_REPORT_OUT:-}" ]; then set -- "$$@" --report-out "$${MEMORY_PUBLIC_BENCHMARK_REPORT_OUT}"; fi; \
	case "$${MEMORY_PUBLIC_BENCHMARK_COMPETITIVE_FLOOR:-}" in 1|true|yes|on) set -- "$$@" --competitive-floor;; esac; \
	$(PYTHON) scripts/official_public_benchmark_canary.py "$$@"

.PHONY: infinity-context-test-quality
infinity-context-test-quality: infinity-context-lint infinity-context-test-all infinity-context-eval
	$(MAKE) infinity-context-secret-scan

.PHONY: infinity-context-secret-scan
infinity-context-secret-scan:
	@! rg -n -P '(?:\b(?:sk-[A-Za-z0-9_-]{40,}|gh[pousr]_[A-Za-z0-9_]{12,}|AKIA[0-9A-Z]{12,})\b|-----BEGIN [A-Z ]*PRIVATE KEY-----)' . \
		-g '!**/__pycache__/**' \
		-g '!tests/**' \
		-g '!frontend/test/**' \
		-g '!*.lock' \
		-g '!uv.lock' \
		-g '!poetry.lock'

.PHONY: infinity-context-prod-confidence
infinity-context-prod-confidence:
	@set -e; \
	cleanup() { $(MAKE) infinity-context-down >/dev/null || true; }; \
	trap cleanup EXIT INT TERM; \
	$(MAKE) infinity-context-plugin-test; \
	$(MAKE) infinity-context-test-quality; \
	$(MAKE) infinity-context-agent-install-doctor; \
	MEMORY_POSTGRES_PORT=$${MEMORY_POSTGRES_PORT:-$(MEMORY_PROD_CONFIDENCE_POSTGRES_PORT)} MEMORY_SERVER_PORT=$${MEMORY_SERVER_PORT:-$(MEMORY_PROD_CONFIDENCE_SERVER_PORT)} $(MAKE) infinity-context-agent-live-smoke; \
	MEMORY_POSTGRES_PORT=$${MEMORY_POSTGRES_PORT:-$(MEMORY_PROD_CONFIDENCE_POSTGRES_PORT)} MEMORY_SERVER_PORT=$${MEMORY_SERVER_PORT:-$(MEMORY_PROD_CONFIDENCE_SERVER_PORT)} $(MAKE) infinity-context-agent-live-smoke-agents; \
	$(MAKE) infinity-context-agent-auth-doctor; \
	git diff --check; \
	$(MAKE) infinity-context-secret-scan

.PHONY: infinity-context-prod-confidence-strict
infinity-context-prod-confidence-strict:
	@set -e; \
	cleanup() { $(MAKE) infinity-context-down >/dev/null || true; }; \
	trap cleanup EXIT INT TERM; \
	$(MAKE) infinity-context-prod-confidence-strict-preflight; \
	$(MAKE) infinity-context-plugin-test; \
	$(MAKE) infinity-context-test-quality; \
	$(MAKE) infinity-context-agent-install-doctor; \
	$(MAKE) infinity-context-top-evidence-bundle; \
	MEMORY_POSTGRES_PORT=$${MEMORY_POSTGRES_PORT:-$(MEMORY_PROD_CONFIDENCE_POSTGRES_PORT)} MEMORY_SERVER_PORT=$${MEMORY_SERVER_PORT:-$(MEMORY_PROD_CONFIDENCE_SERVER_PORT)} $(MAKE) infinity-context-agent-live-smoke; \
	MEMORY_POSTGRES_PORT=$${MEMORY_POSTGRES_PORT:-$(MEMORY_PROD_CONFIDENCE_POSTGRES_PORT)} MEMORY_SERVER_PORT=$${MEMORY_SERVER_PORT:-$(MEMORY_PROD_CONFIDENCE_SERVER_PORT)} $(MAKE) infinity-context-agent-live-smoke-agents-strict; \
	git diff --check; \
	$(MAKE) infinity-context-secret-scan

.PHONY: infinity-context-prod-confidence-full
infinity-context-prod-confidence-full: infinity-context-prod-confidence-strict

.PHONY: infinity-context-prod-confidence-strict-preflight
infinity-context-prod-confidence-strict-preflight:
	$(MAKE) infinity-context-top-evidence-preflight
	$(MAKE) infinity-context-agent-auth-doctor-strict

.PHONY: infinity-context-api-smoke
infinity-context-api-smoke:
	MEMORY_SMOKE_API_URL=$${MEMORY_SMOKE_API_URL:-http://127.0.0.1:7788} MEMORY_SMOKE_AUTH_TOKEN=$${MEMORY_SMOKE_AUTH_TOKEN:-local-dev-token} $(PYTHON) examples/integration_memory_smoke.py

.PHONY: infinity-context-snapshot-thread-smoke
infinity-context-snapshot-thread-smoke:
	MEMORY_SMOKE_API_URL=$${MEMORY_SMOKE_API_URL:-http://127.0.0.1:7788} MEMORY_SMOKE_AUTH_TOKEN=$${MEMORY_SMOKE_AUTH_TOKEN:-local-dev-token} $(PYTHON) scripts/memory_scope_snapshot_thread_smoke.py

.PHONY: infinity-context-mcp-smoke
infinity-context-mcp-smoke:
	MEMORY_MCP_API_URL=$${MEMORY_MCP_API_URL:-http://127.0.0.1:7788} MEMORY_MCP_AUTH_TOKEN=$${MEMORY_MCP_AUTH_TOKEN:-local-dev-token} MEMORY_MCP_WRITE_MODE=direct MEMORY_MCP_DELETE_MODE=explicit MEMORY_MCP_INGEST_MODE=allowed $(PYTHON) examples/mcp_agent_smoke.py

.PHONY: infinity-context-plugin-generate
infinity-context-plugin-generate:
	@set -e; \
	for plugin_root in $(MEMORY_AGENT_PLUGIN_ROOTS); do \
		$(PLUGIN_KIT_AI) generate $$plugin_root; \
	done

.PHONY: infinity-context-plugin-check
infinity-context-plugin-check:
	@set -e; \
	for plugin_root in $(MEMORY_AGENT_PLUGIN_ROOTS); do \
		$(PLUGIN_KIT_AI) generate $$plugin_root --check; \
	done

.PHONY: infinity-context-plugin-validate
infinity-context-plugin-validate:
	@set -e; \
	for target in $(MEMORY_AGENT_PLUGIN_VALIDATE_TARGETS); do \
		echo "Validating Infinity Context agent plugin for $$target"; \
		$(PLUGIN_KIT_AI) validate $(MEMORY_AGENT_PLUGIN_ROOT) --platform $$target --strict; \
	done; \
	for target in $(MEMORY_AGENT_CURSOR_WORKSPACE_PLUGIN_VALIDATE_TARGETS); do \
		echo "Validating Infinity Context agent cursor workspace plugin for $$target"; \
		$(PLUGIN_KIT_AI) validate $(MEMORY_AGENT_CURSOR_WORKSPACE_PLUGIN_ROOT) --platform $$target --strict; \
	done; \
	for target in $(MEMORY_AGENT_GEMINI_HOOK_PLUGIN_VALIDATE_TARGETS); do \
		echo "Validating Infinity Context agent Gemini hooks plugin for $$target"; \
		$(PLUGIN_KIT_AI) validate $(MEMORY_AGENT_GEMINI_HOOK_PLUGIN_ROOT) --platform $$target --strict; \
	done

.PHONY: infinity-context-plugin-doctor
infinity-context-plugin-doctor:
	MEMORY_MCP_API_URL=$${MEMORY_MCP_API_URL:-http://127.0.0.1:7788} MEMORY_MCP_AUTH_TOKEN=$${MEMORY_MCP_AUTH_TOKEN:-local-dev-token} $(MEMORY_AGENT_PLUGIN_ROOT)/bin/infinity-context-mcp-doctor
	MEMORY_MCP_API_URL=$${MEMORY_MCP_API_URL:-http://127.0.0.1:7788} MEMORY_MCP_AUTH_TOKEN=$${MEMORY_MCP_AUTH_TOKEN:-local-dev-token} $(MEMORY_AGENT_CURSOR_WORKSPACE_PLUGIN_ROOT)/bin/infinity-context-mcp-doctor
	MEMORY_MCP_API_URL=$${MEMORY_MCP_API_URL:-http://127.0.0.1:7788} MEMORY_MCP_AUTH_TOKEN=$${MEMORY_MCP_AUTH_TOKEN:-local-dev-token} $(MEMORY_AGENT_GEMINI_HOOK_PLUGIN_ROOT)/bin/infinity-context-mcp-doctor

.PHONY: infinity-context-plugin-e2e
infinity-context-plugin-e2e: infinity-context-plugin-check
	$(PYTHON) -m pytest tests/e2e/test_infinity_context_agent_plugin_e2e.py -q

.PHONY: infinity-context-plugin-test
infinity-context-plugin-test: infinity-context-plugin-check infinity-context-plugin-validate infinity-context-plugin-e2e

.PHONY: infinity-context-capture-test
infinity-context-capture-test:
	$(PYTHON) -m pytest tests/unit/test_capture_api.py tests/unit/test_capture_worker.py tests/unit/test_memory_taxonomy_mapping.py tests/unit/test_schema_migrations.py -q

.PHONY: infinity-context-capture-e2e
infinity-context-capture-e2e:
	$(PYTHON) -m pytest tests/unit/test_capture_api.py tests/unit/test_capture_worker.py -q

.PHONY: infinity-context-hook-capture-smoke
infinity-context-hook-capture-smoke:
	$(PYTHON) -m pytest tests/unit/test_plugin_hook_capture.py tests/unit/test_capture_host_fixtures.py -q

.PHONY: infinity-context-auto-memory-eval
infinity-context-auto-memory-eval:
	$(PYTHON) -m infinity_context_server eval run --suite auto-memory-golden

.PHONY: infinity-context-graph-native-eval
infinity-context-graph-native-eval:
	$(PYTHON) -m infinity_context_server eval run --suite graph-native-golden

.PHONY: infinity-context-auto-memory-quality
infinity-context-auto-memory-quality: infinity-context-capture-test infinity-context-hook-capture-smoke infinity-context-auto-memory-eval infinity-context-graph-native-eval
	$(PYTHON) -m pytest tests/unit/test_mcp_adapter.py -q

.PHONY: infinity-context-agent-install-dry-run
infinity-context-agent-install-dry-run:
	$(PYTHON) scripts/install_memory_agent_plugin.py --dry-run

.PHONY: infinity-context-agent-install
infinity-context-agent-install:
	$(PYTHON) scripts/install_memory_agent_plugin.py

.PHONY: infinity-context-agent-install-doctor
infinity-context-agent-install-doctor:
	$(PLUGIN_KIT_AI) integrations list
	$(PLUGIN_KIT_AI) integrations doctor
	$(PYTHON) scripts/agent_install_verification.py install-doctor

.PHONY: infinity-context-agent-live-smoke
infinity-context-agent-live-smoke:
	MEMORY_POSTGRES_PORT=$${MEMORY_POSTGRES_PORT:-$(MEMORY_AGENT_SMOKE_POSTGRES_PORT)} MEMORY_SERVER_PORT=$${MEMORY_SERVER_PORT:-$(MEMORY_AGENT_SMOKE_SERVER_PORT)} $(MAKE) infinity-context-up-lite
	MEMORY_MCP_API_URL=$${MEMORY_MCP_API_URL:-http://127.0.0.1:$${MEMORY_SERVER_PORT:-$(MEMORY_AGENT_SMOKE_SERVER_PORT)}} MEMORY_MCP_AUTH_TOKEN=$${MEMORY_MCP_AUTH_TOKEN:-local-dev-token} $(PYTHON) scripts/agent_install_verification.py live-smoke

.PHONY: infinity-context-agent-live-smoke-agents
infinity-context-agent-live-smoke-agents:
	MEMORY_POSTGRES_PORT=$${MEMORY_POSTGRES_PORT:-$(MEMORY_AGENT_SMOKE_POSTGRES_PORT)} MEMORY_SERVER_PORT=$${MEMORY_SERVER_PORT:-$(MEMORY_AGENT_SMOKE_SERVER_PORT)} $(MAKE) infinity-context-up-lite
	MEMORY_MCP_API_URL=$${MEMORY_MCP_API_URL:-http://127.0.0.1:$${MEMORY_SERVER_PORT:-$(MEMORY_AGENT_SMOKE_SERVER_PORT)}} MEMORY_MCP_AUTH_TOKEN=$${MEMORY_MCP_AUTH_TOKEN:-local-dev-token} $(PYTHON) scripts/agent_install_verification.py live-smoke --run-agent-cli

.PHONY: infinity-context-agent-live-smoke-agents-strict
infinity-context-agent-live-smoke-agents-strict:
	MEMORY_POSTGRES_PORT=$${MEMORY_POSTGRES_PORT:-$(MEMORY_AGENT_SMOKE_POSTGRES_PORT)} MEMORY_SERVER_PORT=$${MEMORY_SERVER_PORT:-$(MEMORY_AGENT_SMOKE_SERVER_PORT)} $(MAKE) infinity-context-up-lite
	MEMORY_MCP_API_URL=$${MEMORY_MCP_API_URL:-http://127.0.0.1:$${MEMORY_SERVER_PORT:-$(MEMORY_AGENT_SMOKE_SERVER_PORT)}} MEMORY_MCP_AUTH_TOKEN=$${MEMORY_MCP_AUTH_TOKEN:-local-dev-token} $(PYTHON) scripts/agent_install_verification.py live-smoke --run-agent-cli --strict-agent-cli

.PHONY: infinity-context-agent-auth-doctor
infinity-context-agent-auth-doctor:
	$(PYTHON) scripts/agent_install_verification.py agent-auth-doctor

.PHONY: infinity-context-agent-auth-doctor-strict
infinity-context-agent-auth-doctor-strict:
	$(PYTHON) scripts/agent_install_verification.py agent-auth-doctor --strict

.PHONY: infinity-context-agent-auth-repair
infinity-context-agent-auth-repair:
	@if [ ! -t 0 ]; then \
		echo "Run this target from an interactive terminal: make infinity-context-agent-auth-repair"; \
		exit 1; \
	fi
	@echo "Repairing Claude auth through the official Claude CLI login flow..."
	claude auth login --claudeai
	@echo "Repairing OpenCode OpenAI auth through the official OpenCode provider login flow..."
	opencode providers login --provider openai
	$(MAKE) infinity-context-agent-auth-doctor-strict

.PHONY: infinity-context-doctor
infinity-context-doctor:
	$(PYTHON) -m infinity_context_server.doctor

.PHONY: infinity-context-db-upgrade
infinity-context-db-upgrade:
	$(PYTHON) -m infinity_context_server.db upgrade

.PHONY: infinity-context-seed-defaults
infinity-context-seed-defaults:
	$(PYTHON) -m infinity_context_server.admin seed-defaults

.PHONY: infinity-context-worker-once
infinity-context-worker-once:
	$(PYTHON) -m infinity_context_server.worker --once

.PHONY: infinity-context-postgres-up
infinity-context-postgres-up:
	$(COMPOSE) up -d infinity_context_postgres

.PHONY: infinity-context-full-deps-up
infinity-context-full-deps-up:
	$(COMPOSE) --profile full up -d infinity_context_postgres infinity_context_qdrant infinity_context_neo4j

.PHONY: infinity-context-up
infinity-context-up:
	$(MAKE) infinity-context-up-lite

.PHONY: infinity-context-up-lite
infinity-context-up-lite:
	$(COMPOSE) --profile lite up -d infinity_context_server infinity_context_worker infinity_context_extraction_worker

.PHONY: infinity-context-up-full
infinity-context-up-full:
	@test -n "$${MEMORY_OPENAI_API_KEY:-$${OPENAI_API_KEY:-}}" || (echo "Set MEMORY_OPENAI_API_KEY or OPENAI_API_KEY before starting the full profile."; exit 1)
	MEMORY_OPENAI_API_KEY="$${MEMORY_OPENAI_API_KEY:-$${OPENAI_API_KEY}}" OPENAI_API_KEY="$${OPENAI_API_KEY:-$${MEMORY_OPENAI_API_KEY}}" $(COMPOSE) --profile full up -d infinity_context_server_full infinity_context_worker_full infinity_context_extraction_worker_full

.PHONY: infinity-context-selfhost-config
infinity-context-selfhost-config:
	@test -f "$(SELFHOST_ENV)" || (echo "Copy .env.selfhost.example to $(SELFHOST_ENV) and replace change-me values."; exit 1)
	@! grep -Eq '^(MEMORY_SERVICE_TOKEN|MEMORY_POSTGRES_PASSWORD)=change-me' "$(SELFHOST_ENV)" || (echo "Replace MEMORY_SERVICE_TOKEN and MEMORY_POSTGRES_PASSWORD in $(SELFHOST_ENV)."; exit 1)
	$(SELFHOST_COMPOSE) config >/dev/null

.PHONY: infinity-context-selfhost-up
infinity-context-selfhost-up:
	@test -f "$(SELFHOST_ENV)" || (echo "Copy .env.selfhost.example to $(SELFHOST_ENV) and replace change-me values."; exit 1)
	@! grep -Eq '^(MEMORY_SERVICE_TOKEN|MEMORY_POSTGRES_PASSWORD)=change-me' "$(SELFHOST_ENV)" || (echo "Replace MEMORY_SERVICE_TOKEN and MEMORY_POSTGRES_PASSWORD in $(SELFHOST_ENV)."; exit 1)
	$(SELFHOST_COMPOSE) up -d --build

.PHONY: infinity-context-selfhost-up-full
infinity-context-selfhost-up-full:
	@test -f "$(SELFHOST_ENV)" || (echo "Copy .env.selfhost.example to $(SELFHOST_ENV) and replace change-me values."; exit 1)
	@! grep -Eq '^(MEMORY_SERVICE_TOKEN|MEMORY_POSTGRES_PASSWORD)=change-me' "$(SELFHOST_ENV)" || (echo "Replace MEMORY_SERVICE_TOKEN and MEMORY_POSTGRES_PASSWORD in $(SELFHOST_ENV)."; exit 1)
	$(SELFHOST_COMPOSE) --profile full up -d --build

.PHONY: infinity-context-selfhost-down
infinity-context-selfhost-down:
	$(SELFHOST_COMPOSE) down

.PHONY: infinity-context-selfhost-smoke
infinity-context-selfhost-smoke:
	$(PYTHON) scripts/selfhost_smoke.py --env-file "$(SELFHOST_ENV)"

.PHONY: infinity-context-smoke
infinity-context-smoke:
	$(MAKE) infinity-context-up-lite
	for i in $$(seq 1 90); do curl -fsS http://127.0.0.1:7788/v1/health >/dev/null && break; if [ $$i -eq 90 ]; then $(COMPOSE) logs --tail=120 infinity_context_server; exit 1; fi; sleep 1; done
	$(MAKE) infinity-context-api-smoke
	$(MAKE) infinity-context-snapshot-thread-smoke

.PHONY: infinity-context-smoke-full
infinity-context-smoke-full:
	$(MAKE) infinity-context-up-full
	for i in $$(seq 1 120); do curl -fsS http://127.0.0.1:7788/v1/health >/dev/null && break; if [ $$i -eq 120 ]; then $(COMPOSE) logs --tail=120 infinity_context_server_full; exit 1; fi; sleep 1; done
	$(MAKE) infinity-context-api-smoke
	$(MAKE) infinity-context-snapshot-thread-smoke
	$(MAKE) infinity-context-mcp-smoke

.PHONY: infinity-context-clean-full-smoke
infinity-context-clean-full-smoke:
	@test -n "$${MEMORY_OPENAI_API_KEY:-$${OPENAI_API_KEY:-}}" || (echo "Set MEMORY_OPENAI_API_KEY or OPENAI_API_KEY before running clean full smoke."; exit 1)
	export MEMORY_OPENAI_API_KEY="$${MEMORY_OPENAI_API_KEY:-$${OPENAI_API_KEY}}"; \
	export OPENAI_API_KEY="$${OPENAI_API_KEY:-$${MEMORY_OPENAI_API_KEY}}"; \
	$(PYTHON) scripts/clean_full_smoke.py

.PHONY: infinity-context-clean-full-mcp-smoke
infinity-context-clean-full-mcp-smoke:
	@test -n "$${MEMORY_OPENAI_API_KEY:-$${OPENAI_API_KEY:-}}" || (echo "Set MEMORY_OPENAI_API_KEY or OPENAI_API_KEY before running clean full MCP smoke."; exit 1)
	export MEMORY_CLEAN_SMOKE_SKIP_MCP=false; \
	export MEMORY_OPENAI_API_KEY="$${MEMORY_OPENAI_API_KEY:-$${OPENAI_API_KEY}}"; \
	export OPENAI_API_KEY="$${OPENAI_API_KEY:-$${MEMORY_OPENAI_API_KEY}}"; \
	$(PYTHON) scripts/clean_full_smoke.py

.PHONY: infinity-context-agent-behavior-bench
infinity-context-agent-behavior-bench:
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

.PHONY: infinity-context-agent-realistic-bench
infinity-context-agent-realistic-bench:
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

.PHONY: infinity-context-agent-live-session-bench
infinity-context-agent-live-session-bench:
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

.PHONY: infinity-context-agent-transcript-corpus-bench
infinity-context-agent-transcript-corpus-bench:
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

.PHONY: infinity-context-agent-transcript-corpus-redact
infinity-context-agent-transcript-corpus-redact:
	@test -n "$${MEMORY_AGENT_TRANSCRIPT_INPUT:-}" || (echo "Set MEMORY_AGENT_TRANSCRIPT_INPUT to a transcript file or directory."; exit 1)
	@test -n "$${MEMORY_AGENT_TRANSCRIPT_OUTPUT:-}" || (echo "Set MEMORY_AGENT_TRANSCRIPT_OUTPUT to the redacted corpus output directory."; exit 1)
	$(PYTHON) scripts/agent_transcript_corpus_redactor.py "$${MEMORY_AGENT_TRANSCRIPT_INPUT}" "$${MEMORY_AGENT_TRANSCRIPT_OUTPUT}"

.PHONY: infinity-context-agent-transcript-corpus-audit
infinity-context-agent-transcript-corpus-audit:
	@test -n "$${MEMORY_AGENT_BENCH_TRANSCRIPT_CORPUS_DIR:-}" || (echo "Set MEMORY_AGENT_BENCH_TRANSCRIPT_CORPUS_DIR to a redacted corpus directory."; exit 1)
	@if [ "$${MEMORY_AGENT_TRANSCRIPT_CORPUS_AUDIT_STRICT:-false}" = "true" ]; then \
		$(PYTHON) scripts/agent_transcript_corpus_audit.py "$${MEMORY_AGENT_BENCH_TRANSCRIPT_CORPUS_DIR}" --strict; \
	else \
		$(PYTHON) scripts/agent_transcript_corpus_audit.py "$${MEMORY_AGENT_BENCH_TRANSCRIPT_CORPUS_DIR}"; \
	fi

.PHONY: infinity-context-full-provider-canary
infinity-context-full-provider-canary: infinity-context-clean-full-mcp-smoke

.PHONY: infinity-context-full-provider-public-benchmark-canary
infinity-context-full-provider-public-benchmark-canary:
	@test -n "$${MEMORY_OPENAI_API_KEY:-$${OPENAI_API_KEY:-}}" || (echo "Set MEMORY_OPENAI_API_KEY or OPENAI_API_KEY before running full-provider public benchmark canary."; exit 1)
	export MEMORY_CLEAN_SMOKE_PUBLIC_BENCHMARK=true; \
	export MEMORY_CLEAN_SMOKE_SKIP_MCP=false; \
	export MEMORY_PUBLIC_BENCHMARK_NAME="$${MEMORY_PUBLIC_BENCHMARK_NAME:-locomo}"; \
	export MEMORY_PUBLIC_BENCHMARK_MAX_CASES="$${MEMORY_PUBLIC_BENCHMARK_MAX_CASES:-1}"; \
	export MEMORY_PUBLIC_BENCHMARK_MIN_ACCURACY="$${MEMORY_PUBLIC_BENCHMARK_MIN_ACCURACY:-0.5}"; \
	export MEMORY_OPENAI_API_KEY="$${MEMORY_OPENAI_API_KEY:-$${OPENAI_API_KEY}}"; \
	export OPENAI_API_KEY="$${OPENAI_API_KEY:-$${MEMORY_OPENAI_API_KEY}}"; \
	$(PYTHON) scripts/clean_full_smoke.py

.PHONY: infinity-context-full-provider-public-benchmark-suite
infinity-context-full-provider-public-benchmark-suite:
	@test -n "$${MEMORY_PUBLIC_BENCHMARK_LOCOMO_DATASET:-}" || (echo "Set MEMORY_PUBLIC_BENCHMARK_LOCOMO_DATASET to a representative LoCoMo dataset before running public benchmark suite."; exit 1)
	@test -n "$${MEMORY_PUBLIC_BENCHMARK_LONGMEMEVAL_DATASET:-}" || (echo "Set MEMORY_PUBLIC_BENCHMARK_LONGMEMEVAL_DATASET to a representative LongMemEval dataset before running public benchmark suite."; exit 1)
	MEMORY_PUBLIC_BENCHMARK_NAME="$${MEMORY_PUBLIC_BENCHMARK_NAME:-all}" \
	MEMORY_PUBLIC_BENCHMARK_MAX_CASES="$${MEMORY_PUBLIC_BENCHMARK_MAX_CASES:-600}" \
	MEMORY_PUBLIC_BENCHMARK_MIN_ACCURACY="$${MEMORY_PUBLIC_BENCHMARK_MIN_ACCURACY:-0.947}" \
	MEMORY_PUBLIC_BENCHMARK_COMPETITIVE_FLOOR="$${MEMORY_PUBLIC_BENCHMARK_COMPETITIVE_FLOOR:-true}" \
	$(MAKE) infinity-context-full-provider-public-benchmark-canary

.PHONY: infinity-context-full-provider-canary-interactive
infinity-context-full-provider-canary-interactive:
	@if [ -n "$${MEMORY_OPENAI_API_KEY:-$${OPENAI_API_KEY:-}}" ]; then \
		$(MAKE) infinity-context-full-provider-canary; \
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
		MEMORY_OPENAI_API_KEY="$$OPENAI_KEY" OPENAI_API_KEY="$$OPENAI_KEY" $(MAKE) infinity-context-full-provider-canary; \
		unset OPENAI_KEY; \
	fi

.PHONY: infinity-context-prod-load-canary
infinity-context-prod-load-canary:
	@test -n "$${MEMORY_OPENAI_API_KEY:-$${OPENAI_API_KEY:-}}" || (echo "Set MEMORY_OPENAI_API_KEY or OPENAI_API_KEY before running prod load canary."; exit 1)
	export MEMORY_CLEAN_SMOKE_PROD_LOAD=true; \
	export MEMORY_CLEAN_SMOKE_SKIP_MCP=false; \
	export MEMORY_CLEAN_SMOKE_WORKER_TIMEOUT_SECONDS="$${MEMORY_CLEAN_SMOKE_WORKER_TIMEOUT_SECONDS:-420}"; \
	export MEMORY_OPENAI_API_KEY="$${MEMORY_OPENAI_API_KEY:-$${OPENAI_API_KEY}}"; \
	export OPENAI_API_KEY="$${OPENAI_API_KEY:-$${MEMORY_OPENAI_API_KEY}}"; \
	$(PYTHON) scripts/clean_full_smoke.py

.PHONY: infinity-context-real-memory-confidence
infinity-context-real-memory-confidence:
	@set -e; \
	cleanup() { $(MAKE) infinity-context-down >/dev/null || true; }; \
	trap cleanup EXIT INT TERM; \
	$(MAKE) infinity-context-top-evidence-bundle; \
	$(MAKE) infinity-context-prod-load-canary; \
	$(MAKE) infinity-context-agent-live-session-bench; \
	$(MAKE) infinity-context-agent-transcript-corpus-bench; \
	git diff --check; \
	$(MAKE) infinity-context-secret-scan

.PHONY: infinity-context-down
infinity-context-down:
	$(COMPOSE) --profile lite --profile full down

.PHONY: infinity-context-server
infinity-context-server:
	$(MEMORY_SERVER_ENV) $(PYTHON) -m infinity_context_server.main
