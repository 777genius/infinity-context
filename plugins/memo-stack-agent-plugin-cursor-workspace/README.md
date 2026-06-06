# Memory Agent Plugin Cursor Workspace

MCP-only Cursor workspace plugin for Memo Stack.

This plugin exists because `plugin-kit-ai` 1.2.2 supports portable MCP for the
`cursor-workspace` target, but does not support portable skills there. The main
`memo-stack-agent-plugin` keeps skills for package-capable agents. This sibling
plugin keeps Cursor workspace validation clean.

The generated `.cursor/mcp.json` is meant to be used from the Memo Stack
repository root. Its command points at:

```text
${workspaceFolder}/plugins/memo-stack-agent-plugin-cursor-workspace/bin/memo-stack-mcp
```

For a different consuming workspace, keep the env contract but point `command`
at the checked-out Memo Stack plugin wrapper.

## Install Into Cursor Workspace

For this repository:

```bash
mkdir -p .cursor
cp plugins/memo-stack-agent-plugin-cursor-workspace/.cursor/mcp.json .cursor/mcp.json
```

For another repository, copy or merge the generated `mcpServers.memo-stack`
entry into that repository's `.cursor/mcp.json`, then change `command` to an
absolute path for this Memo Stack checkout.

## Local Run

From the Memo Stack repository root:

```bash
make memo-stack-up-lite
MEMORY_MCP_API_URL=http://127.0.0.1:7788 \
MEMORY_MCP_AUTH_TOKEN=local-dev-token \
plugins/memo-stack-agent-plugin-cursor-workspace/bin/memo-stack-mcp-doctor
```

The generated MCP config uses `MEMORY_MCP_DEFAULT_THREAD_EXTERNAL_REF` with the
`__MEMO_STACK_NO_DEFAULT_THREAD__` sentinel. The wrapper unsets this value
before starting MCP, so the runtime default remains no thread scope.

## Generate And Validate

```bash
plugin-kit-ai generate plugins/memo-stack-agent-plugin-cursor-workspace
plugin-kit-ai generate plugins/memo-stack-agent-plugin-cursor-workspace --check
plugin-kit-ai validate plugins/memo-stack-agent-plugin-cursor-workspace --platform cursor-workspace --strict
```
