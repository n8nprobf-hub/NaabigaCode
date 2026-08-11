"""Compatibility shim — ``hermes_constants`` for vendored gateway code.

Maps upstream Hermes constant/function names onto the Naabiga equivalents
(``naabiga_constants``). Kept as a thin re-export layer; no new logic.

⚠️ Les ré-exports portent ``# noqa: F401`` — ils sont utilisés par le
gateway vendu (gateway/*), pas par ce fichier lui-même. Ne pas laisser
``ruff --fix`` les supprimer.
"""

from naabiga_constants import (  # noqa: F401 — ré-exports pour gateway vendu
    VALID_REASONING_EFFORTS,
    apply_ipv4_preference as apply_ipv,
    display_naabiga_home as display_hermes_home,
    get_default_naabiga_root as get_default_hermes_root,
    get_naabiga_dir as get_hermes_dir,
    get_naabiga_home as get_hermes_home,
    _get_platform_default_naabiga_home as _get_platform_default_hermes_home,
    get_naabiga_home_override as get_hermes_home_override,
    get_optional_skills_dir,
    parse_reasoning_effort,
    set_naabiga_home_override as set_hermes_home_override,
    reset_naabiga_home_override as reset_hermes_home_override,
)

# resolve_reasoning_config has no Naabiga equivalent yet; re-export the
# upstream implementation (imported lazily to avoid a hard dependency on
# the full naabiga_cli config stack at import time).
def resolve_reasoning_config(cfg: dict | None, model: str = ""):
    """Resolve effective reasoning config — upstream-compatible shim."""
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