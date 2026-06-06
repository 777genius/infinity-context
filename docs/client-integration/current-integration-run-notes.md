# Client App Integration Run Notes

These notes were copied from the Client App project context when Memo Stack docs were moved out.

## Current Client App Memory Integration

Client App currently has desktop interview memory behavior around `ActiveContext`.

Backend routes:

```text
/api/v1/interview-memory/ingest
/api/v1/interview-memory/context
```

Backend config requirement:

```text
INTERVIEW_MEMORY__ENABLED=true
```

Desktop bridge behavior:

- calls `/api/v1/interview-memory/ingest` and `/api/v1/interview-memory/context`;
- ingest is best-effort;
- context retrieval falls back to local context when backend memory fails;
- resolved memory mode defaults to `active_context` when unset;
- settings switch `AppConfig.interview_memory_enabled=false` disables runtime memory without restart.

Supported desktop modes:

```text
disabled
shadow_ingest
shadow_retrieve
assistive_context
active_context
local_only
```

Kill switches:

```text
INTERVIEW_MEMORY_FORCE_DISABLED=true
INTERVIEW_MEMORY_ENABLED=false
INTERVIEW_MEMORY_ACTIVE_CONTEXT=false
INTERVIEW_MEMORY_FORCE_LOCAL_ONLY=true
```

Memory-only backend override:

```bash
INTERVIEW_MEMORY_API_URL=http://127.0.0.1:8080
INTERVIEW_MEMORY_AUTH_TOKEN=<local-user-jwt>
```

Production-backend desktop run:

```bash
pnpm copy-helper:brave:restart-cdp
VITE_API_URL=https://api.voicetext.site \
VOICE_TO_TEXT_BACKEND_URL=wss://api.voicetext.site \
FOCUS_COPY_ENABLE_BROWSER_CDP=1 \
pnpm tauri dev
```

Local memory backend canary while STT remains production:

```bash
INTERVIEW_MEMORY_API_URL=http://127.0.0.1:8080 \
INTERVIEW_MEMORY_AUTH_TOKEN=<local-user-jwt> \
VITE_API_URL=https://api.voicetext.site \
VOICE_TO_TEXT_BACKEND_URL=wss://api.voicetext.site \
FOCUS_COPY_ENABLE_BROWSER_CDP=1 \
pnpm tauri dev
```

## Future Memo Stack Compatibility Goal

The new Memo Stack should preserve Client App compatibility through an adapter/gateway instead of making Client App own the memory engine.

Target boundary:

```text
Client App desktop/backend
  -> HTTP or SDK
  -> memo_stack_server compatibility routes
  -> memo_stack_core use cases
  -> Postgres canonical truth + Qdrant/Graphiti derived indexes
```

Rules:

- Client App must not import Qdrant/Graphiti provider SDKs;
- compatibility DTOs stay in `memo_stack_server`, not `memo_stack_core`;
- fallback behavior remains best-effort and non-blocking;
- active prompt path must keep kill switches;
- local-only mode must avoid remote memory calls.
