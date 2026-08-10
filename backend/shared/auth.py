"""Lazy re-exports for auth utilities.

Breaks the top-level circular dependency: agent/ imports from shared/
instead of naabiga_cli/ directly.

Uses module-level __getattr__ (PEP 562) so that ``from shared.auth import X``
and ``import shared.auth as _auth`` both resolve attributes lazily from
naabiga_cli.auth on first access.
"""

from __future__ import annotations

import importlib as _importlib

_SOURCE = "naabiga_cli.auth"


def __getattr__(name: str):
    """Lazy attribute access: delegates to naabiga_cli.auth."""
    mod = _importlib.import_module(_SOURCE)
    try:
        return getattr(mod, name)
    except AttributeError:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from None
