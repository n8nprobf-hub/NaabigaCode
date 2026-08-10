"""Compatibility shim — ``hermes_constants`` for vendored gateway code.

Maps upstream Hermes constant/function names onto the Naabiga equivalents
(``naabiga_constants``). Kept as a thin re-export layer; no new logic.
"""

from naabiga_constants import (
    parse_reasoning_effort,
)

# resolve_reasoning_config has no Naabiga equivalent yet; re-export the
# upstream implementation (imported lazily to avoid a hard dependency on
# the full naabiga_cli config stack at import time).
def resolve_reasoning_config(cfg: dict | None, model: str = ""):
    """Resolve effective reasoning config — upstream-compatible shim."""
    from hermes_cli import config as _hc_config  # noqa: F401  (alias to naabiga_cli.config)

    from naabiga_cli.config import cfg_get as _cfg_get

    if not cfg:
        return None
    overrides = _cfg_get(cfg, "agent", "reasoning_overrides", default={}) or {}
    if isinstance(overrides, dict) and model in overrides:
        return overrides[model]
    effort = _cfg_get(cfg, "agent", "reasoning_effort", default=None)
    if effort is None:
        return None
    return {"reasoning_effort": parse_reasoning_effort(effort)}
