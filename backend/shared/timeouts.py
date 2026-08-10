"""Lazy re-exports for timeout configuration.

Breaks the top-level circular dependency: agent/ imports from shared/
instead of naabiga_cli/ directly.
"""

from __future__ import annotations


def get_provider_request_timeout(*args, **kwargs):
    """Lazy re-export of naabiga_cli.timeouts.get_provider_request_timeout."""
    from naabiga_cli.timeouts import get_provider_request_timeout as _fn
    return _fn(*args, **kwargs)


def get_provider_stale_timeout(*args, **kwargs):
    """Lazy re-export of naabiga_cli.timeouts.get_provider_stale_timeout."""
    from naabiga_cli.timeouts import get_provider_stale_timeout as _fn
    return _fn(*args, **kwargs)
