"""Shared utilities for the NaabigaCode backend.

This package breaks the circular dependency between ``agent/`` and
``naabiga_cli/`` by providing stable import paths for cross-cutting
utilities (subprocess compat, timeouts, config access, auth helpers).

The agent modules import from ``shared/`` rather than ``naabiga_cli/``
directly.  ``shared/`` re-exports from ``naabiga_cli/`` with lazy imports
(function-level or PEP 562 __getattr__) so the top-level circular
dependency disappears.
"""
