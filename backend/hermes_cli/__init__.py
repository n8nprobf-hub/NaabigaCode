"""Compatibility shim — ``hermes_cli`` namespace for vendored gateway code.

NaabigaCode is a rebrand of the upstream Hermes agent. The vendored
``gateway/`` package (platforms, sessions, delivery) still imports
``hermes_cli.*`` symbols. This package provides those symbols by
re-exporting the Naabiga equivalents (``naabiga_cli``) plus a small set
of upstream modules that have no Naabiga counterpart yet.

Do NOT add new code here — this is a bridging layer only.
"""

from importlib import import_module
import sys

__version__ = "0.2.0"

# Sub-modules that exist in naabiga_cli: alias them so
# ``hermes_cli.<name>`` resolves to the Naabiga implementation.
_ALIASED = [
    "_subprocess_compat",
    "auth",
    "commands",
    "debug",
    "fallback_config",
    "gateway",
    "gateway_windows",
    "goals",
    "inventory",
    "kanban",
    "main",
    "moa_config",
    "model_cost_guard",
    "model_normalize",
    "model_switch",
    "models",
    "plugins",
    "profiles",
    "providers",
    "runtime_provider",
    "security_advisories",
    "skin_engine",
    "stdio",
    "tools_config",
]

for _name in _ALIASED:
    try:
        _mod = import_module(f"naabiga_cli.{_name}")
    except Exception:  # pragma: no cover — defensive
        continue
    sys.modules[f"{__name__}.{_name}"] = _mod
