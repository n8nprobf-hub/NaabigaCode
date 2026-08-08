# Langfuse Observability Plugin

This plugin ships bundled with Naabiga but is **opt-in** — it only loads when
you explicitly enable it.

## Enable

Pick one:

```bash
# Interactive: walks you through credentials + SDK install + enable
naabiga tools  # → Langfuse Observability

# Manual
pip install langfuse
naabiga plugins enable observability/langfuse
```

## Required credentials

Set these in `~/.naabiga/.env` (or via `naabiga tools`):

```bash
NAABIGA_LANGFUSE_PUBLIC_KEY=pk-lf-...
NAABIGA_LANGFUSE_SECRET_KEY=sk-lf-...
NAABIGA_LANGFUSE_BASE_URL=https://cloud.langfuse.com   # or your self-hosted URL
```

Without the SDK or credentials the hooks no-op silently — the plugin fails
open.

## Verify

```bash
naabiga plugins list                 # observability/langfuse should show "enabled"
naabiga chat -q "hello"              # then check Langfuse for a "Naabiga turn" trace
```

## Optional tuning

```bash
NAABIGA_LANGFUSE_ENV=production       # environment tag
NAABIGA_LANGFUSE_RELEASE=v1.0.0       # release tag
NAABIGA_LANGFUSE_SAMPLE_RATE=0.5      # sample 50% of traces
NAABIGA_LANGFUSE_MAX_CHARS=12000      # max chars per field (default: 12000)
NAABIGA_LANGFUSE_DEBUG=true           # verbose plugin logging
```

## Disable

```bash
naabiga plugins disable observability/langfuse
```
