# Memo Stack Gemini Hooks Plugin

This is the Gemini-specific hook lane for Memo Stack agent memory.

The universal `plugins/memo-stack-agent-plugin` package keeps portable MCP and
skills for Codex, Claude, Gemini, OpenCode, and Cursor. Gemini lifecycle hooks
need a different `hooks/hooks.json` ABI than Claude and Codex, so this package
is intentionally target-specific instead of sharing the universal root hook
artifact.

## Runtime

The extension reuses the repo-local wrappers:

```bash
plugins/memo-stack-agent-plugin-gemini-hooks/bin/memo-stack-mcp
plugins/memo-stack-agent-plugin-gemini-hooks/bin/memo-stack-plugin-hook
```

`memo-stack-plugin-hook` writes Gemini hook JSON to stdout. Diagnostics go to
stderr only. The default behavior is retrieve-only and fail-open.

## Hook Events

- `SessionStart` - optional session context.
- `BeforeAgent` - turn-local memory context through `additionalContext`.
- `AfterAgent` - opt-in capture source when `MEMORY_PLUGIN_HOOK_INGEST_EVENTS=AfterAgent`.
- `SessionEnd` - opt-in capture source when `MEMORY_PLUGIN_HOOK_INGEST_EVENTS=SessionEnd`.

No model or tool hooks are wired in the first lane because Memo Stack memory
does not need to rewrite model/tool payloads. Keeping those out avoids latency
and unexpected control-flow side effects.

## Safe Defaults

```bash
MEMORY_AUTO_MEMORY_MODE=retrieve_only
MEMORY_PLUGIN_HOOK_CONTEXT_EVENTS=SessionStart,BeforeAgent
MEMORY_PLUGIN_HOOK_INGEST_EVENTS=
MEMORY_PLUGIN_HOOK_TRANSCRIPT_TAIL_MODE=off
```

To enable review-gated capture:

```bash
MEMORY_AUTO_MEMORY_MODE=suggest
MEMORY_PLUGIN_HOOK_INGEST_EVENTS=BeforeAgent,AfterAgent,SessionEnd
```

Captures go to `/v1/captures` and then through the server-side consolidation
pipeline. They are not directly written as active facts by the hook process.

## Development

```bash
plugin-kit-ai generate plugins/memo-stack-agent-plugin-gemini-hooks
plugin-kit-ai validate plugins/memo-stack-agent-plugin-gemini-hooks --platform gemini --strict
```
