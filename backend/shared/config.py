"""Lazy re-exports for configuration access.

Breaks the top-level circular dependency: agent/ imports from shared/
instead of naabiga_cli/ directly.
"""

from __future__ import annotations


def load_env(*args, **kwargs):
    """Lazy re-export of naabiga_cli.config.load_env."""
    from naabiga_cli.config import load_env as _fn
    return _fn(*args, **kwargs)


def cfg_get(*args, **kwargs):
    """Lazy re-export of naabiga_cli.config.cfg_get."""
    from naabiga_cli.config import cfg_get as _fn
    return _fn(*args, **kwargs)


def get_naabiga_home(*args, **kwargs):
    """Lazy re-export of naabiga_cli.config.get_naabiga_home."""
    from naabiga_cli.config import get_naabiga_home as _fn
    return _fn(*args, **kwargs)


def load_config(*args, **kwargs):
    """Lazy re-export of naabiga_cli.config.load_config."""
    from naabiga_cli.config import load_config as _fn
    return _fn(*args, **kwargs)
