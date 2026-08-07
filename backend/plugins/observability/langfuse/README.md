# Langfuse Observability Plugin

This plugin ships bundled with Thot but is **opt-in** — it only loads when
you explicitly enable it.

## Enable

Pick one:

```bash
# Interactive: walks you through credentials + SDK install + enable
thot tools  # → Langfuse Observability

# Manual
pip install langfuse
thot plugins enable observability/langfuse
```

## Required credentials

Set these in `~/.thot/.env` (or via `thot tools`):

```bash
THOT_LANGFUSE_PUBLIC_KEY=pk-lf-...
THOT_LANGFUSE_SECRET_KEY=sk-lf-...
THOT_LANGFUSE_BASE_URL=https://cloud.langfuse.com   # or your self-hosted URL
```

Without the SDK or credentials the hooks no-op silently — the plugin fails
open.

## Verify

```bash
thot plugins list                 # observability/langfuse should show "enabled"
thot chat -q "hello"              # then check Langfuse for a "Thot turn" trace
```

## Optional tuning

```bash
THOT_LANGFUSE_ENV=production       # environment tag
THOT_LANGFUSE_RELEASE=v1.0.0       # release tag
THOT_LANGFUSE_SAMPLE_RATE=0.5      # sample 50% of traces
THOT_LANGFUSE_MAX_CHARS=12000      # max chars per field (default: 12000)
THOT_LANGFUSE_DEBUG=true           # verbose plugin logging
```

## Disable

```bash
thot plugins disable observability/langfuse
```
