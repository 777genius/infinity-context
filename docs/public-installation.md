# Public installation and first run

Infinity Context 0.1.0 is distributed as a local installer, a Python package,
and a multi-architecture container image. The local installer is the recommended
path when you want the complete self-hosted runtime, agent connection, and UI.

## Recommended local install

Requirements: Git, Python 3.11 or later, and Docker with Compose.

Download the versioned installer so it can be inspected before execution:

```bash
curl -fsSLo infinity-context-install.sh \
  https://raw.githubusercontent.com/777genius/infinity-context/v0.1.0/scripts/install.sh
less infinity-context-install.sh
bash infinity-context-install.sh --agent codex
```

Repeat `--agent` to connect more agents, or use `--all-agents`. The normal mode
creates review-gated memory suggestions and opens the UI after readiness. It does
not silently apply captured memory.

Useful safety and control options:

```bash
# Inspect all planned installer actions without changing the machine.
bash infinity-context-install.sh --dry-run --agent codex

# Install the checkout and CLI only; do not start services or touch agent config.
bash infinity-context-install.sh --no-start --no-agent-tools

# Keep recall but disable automatic capture creation.
bash infinity-context-install.sh --retrieve-only --agent codex

# Keep recall and require explicit MCP memory suggestions.
bash infinity-context-install.sh --manual-memory --agent codex

# Configure all supported agents but do not open the browser UI.
bash infinity-context-install.sh --all-agents --no-open-ui
```

Supported agent targets are Codex, Claude, Gemini, OpenCode, and Cursor. Restart
an agent after its integration has been confirmed so it can load the new MCP and
hook configuration.

## PyPI and pipx

Use pipx when you need the CLI, SDK, MCP server, or want to connect to an
existing Infinity Context deployment:

```bash
pipx install 'infinity-context[mcp]==0.1.0'
infinity-context --version
```

The Python distribution does not embed the Docker Compose project. Use the local
installer above for a complete first-run local stack, or provide an existing
service URL to the installed tools.

## Container image

The release workflow publishes build provenance and a multi-architecture image
for Linux AMD64 and ARM64:

```bash
docker pull ghcr.io/777genius/infinity-context:0.1.0
```

The image contains the Infinity Context server. Postgres remains the canonical
store and must be configured externally; the versioned Compose stack installed
by the recommended installer provides the complete local topology.

## Automatic memory policy

The default `suggest` mode listens only at durable lifecycle boundaries supported
by each agent. It redacts sensitive text, ignores raw tool noise, keeps transcript
tail capture off, and sends candidates to review. Users can pause creation with
`--retrieve-only`, switch to explicit writes with `--manual-memory`, review or
reject suggestions in the UI, and remove accepted memory through the canonical
lifecycle APIs.
