# Infinity Context

**Shared project memory for AI agents, with sources you can inspect and changes you can review.**

Keep decisions, documents, and project knowledge available across sessions and
agents. Infinity Context runs on your infrastructure and gives your team one
place to capture knowledge, review updates, and recall relevant context.

[Quickstart](#quickstart) · [Integrations](#integrate-with-your-app) · [Documentation](docs/README.md)

## Why use it?

- **Continue where work left off.** Give a new session the relevant project
  decisions and evidence without copying an entire conversation.
- **Share knowledge across agents.** Connect several coding agents to the same
  memory while keeping projects and threads scoped.
- **Review what becomes memory.** Automatic capture creates suggestions for
  review before promotion to durable knowledge.
- **Follow the source.** Retrieved context includes citations and provenance so
  people and agents can check the evidence.
- **Keep knowledge current.** Updates and forget operations affect canonical
  visibility, even while search indexes catch up.

The everyday loop: **capture → review → recall → update**.
The local UI lets you browse knowledge and review suggestions alongside your
agent workflow.

## Quickstart

Requires **Git, Python 3.11+, and Docker with Compose**.

Download the versioned installer, then connect your agent:

```bash
curl -fsSLo infinity-context-install.sh \
  https://raw.githubusercontent.com/777genius/infinity-context/v0.2.0/scripts/install.sh
bash infinity-context-install.sh --agent codex
```

The installer starts the local stack, configures the requested agent
integration, and opens the memory UI. It reports any integration that still
needs manual setup.

### Supported coding agents

| Agent | Installer option |
| --- | --- |
| Codex | `--agent codex` |
| Claude Code | `--agent claude` |
| Gemini CLI | `--agent gemini` |
| OpenCode | `--agent opencode` |
| Cursor | `--agent cursor` |

Repeat `--agent` to connect several agents, or use `--all-agents`.
Use `--retrieve-only` to enable recall without automatic capture, or
`--no-agent-tools` to keep agent configuration unchanged.

See [installation and first run](docs/public-installation.md) for installation options,
capture controls, and upgrade guidance.

> Upgrading from v0.1.0? Back up the existing Postgres container before
> recreating it. Follow the [data persistence and upgrade notes](docs/public-installation.md#data-persistence-and-v010-upgrades).

## Integrate with your app

Use the HTTP API or an SDK to add memory to an application. Coding agents can
use the MCP server; people can use the CLI and local UI.

| Entry point | Start here |
| --- | --- |
| Python SDK, CLI, and MCP | `pipx install 'infinity-context[mcp]==0.2.0'` |
| TypeScript SDK | [SDK README](packages/infinity_context_ts_sdk/README.md) and [release guide](docs/typescript-sdk-release.md) |
| HTTP API | [API and integration documentation](docs/README.md) |
| Agent tools and resources | [MCP adapter guide](docs/mcp-adapter.md) |

The service and Python package are versioned together at **0.2.0**.
The TypeScript SDK has its own release line, **0.3.2**; follow its release guide
for installation and artifact verification.

For a container deployment:

```bash
docker pull ghcr.io/777genius/infinity-context:0.2.0
```

For development from source:

```bash
git clone https://github.com/777genius/infinity-context.git
cd infinity-context
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[mcp]'
.venv/bin/infinity-context quickstart --agent codex --open-ui
```

## How memory stays trustworthy

Postgres holds the canonical memory state. Optional Qdrant and Graphiti
indexes help find candidates; each result is checked against current scope,
visibility, and lifecycle state before it enters context.

Retrieved memory is rendered as **cited evidence**, never as instructions for
the model. Source references establish provenance; review and judgment are
still needed to decide whether a claim is true.

Read the [architecture and trust model](docs/architecture-and-trust-model.md)
for consistency guarantees, adapter boundaries, and security limits.

## Status

**Alpha, under active development.** APIs and deployment details may change.
Evaluate retrieval quality and operational fit on your own workload before
production use. Current diagnostics do not establish broad answer accuracy or
large-scale production readiness.

Optional adapters have different capability limits; the Graphiti adapter is a
current-state projection. Cognitive memory remains a foundation rather than a
complete runtime feature. For shared deployments, configure access control and
backups using the [deployment guide](docs/self-hosted-team-deployment.md).

## Explore further

- [Documentation index](docs/README.md)
- [Installation and first run](docs/public-installation.md)
- [Self-hosted team deployment](docs/self-hosted-team-deployment.md)
- [Architecture and trust model](docs/architecture-and-trust-model.md)
- [Evaluation evidence and limitations](docs/quality-analysis/memory-quality-e2e-20261022.md)
- [Agent memory capability comparison](docs/competitive/agent-memory-capability-comparison.md)
