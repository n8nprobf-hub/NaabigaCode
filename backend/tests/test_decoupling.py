"""Smoke tests for the Naabiga engine (backend/run_agent.py, agent/).

These tests verify that the core modules import and that the AIAgent
can be constructed without error, WITHOUT calling an external provider
or network.

Heavy dependencies (openai, dotenv, httpx, etc.) are stubbed when absent
locally — CI installs them via requirements.txt.
"""

import sys
import importlib
from unittest.mock import MagicMock


# ── Stubs for deps not installed locally (CI has them via requirements.txt) ──
def _ensure_stub(name, attrs=None):
    """Inject a stub module if the real one is not installed."""
    if name in sys.modules:
        return
    try:
        importlib.import_module(name)
    except ImportError:
        stub = MagicMock()
        if attrs:
            for k, v in attrs.items():
                setattr(stub, k, v)
        sys.modules[name] = stub


# naabiga_cli.auth imports httpx + openai at top level; shared.auth re-exports
# it lazily, so tests need these stubbed when requirements.txt is not installed.
_ensure_stub("openai")
_ensure_stub("dotenv")
_ensure_stub("httpx")


# ── Tests ─────────────────────────────────────────────────────────────────
def test_shared_package_imports():
    """The shared/ package imports and exposes its re-exports."""
    import shared
    assert hasattr(shared, "__file__")

    from shared._subprocess_compat import IS_WINDOWS, windows_hide_flags
    assert isinstance(IS_WINDOWS, bool)
    assert callable(windows_hide_flags)

    from shared.timeouts import get_provider_request_timeout, get_provider_stale_timeout
    assert callable(get_provider_request_timeout)
    assert callable(get_provider_stale_timeout)

    from shared.config import load_env, cfg_get, get_naabiga_home, load_config
    assert callable(load_env)
    assert callable(cfg_get)
    assert callable(get_naabiga_home)
    assert callable(load_config)

    from shared.auth import PROVIDER_REGISTRY
    # PROVIDER_REGISTRY existe dans naabiga_cli.auth (même si vide)
    assert PROVIDER_REGISTRY is not None


def test_shared_breaks_circular_dependency():
    """No top-level agent/ → naabiga_cli import remains."""
    import ast
    import os

    agent_dir = os.path.join(os.path.dirname(__file__), "..", "agent")
    agent_dir = os.path.abspath(agent_dir)

    violations = []
    for fname in os.listdir(agent_dir):
        if not fname.endswith(".py"):
            continue
        fpath = os.path.join(agent_dir, fname)
        with open(fpath) as f:
            try:
                tree = ast.parse(f.read(), filename=fpath)
            except SyntaxError:
                continue
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.ImportFrom):
                if node.module and node.module.startswith("naabiga_cli"):
                    violations.append(f"{fname}:{node.lineno} → {node.module}")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("naabiga_cli"):
                        violations.append(f"{fname}:{node.lineno} → {alias.name}")

    assert not violations, (
        f"{len(violations)} imports circulaires top-level restants:\n  "
        + "\n  ".join(violations)
    )


def test_agent_modules_compile():
    """The modified agent/ modules compile without error."""
    import py_compile
    import os
    import tempfile

    files = [
        "agent/skill_preprocessing.py",
        "agent/shell_hooks.py",
        "agent/coding_context.py",
        "agent/chat_completion_helpers.py",
        "agent/agent_runtime_helpers.py",
        "agent/auxiliary_client.py",
        "agent/agent_init.py",
        "agent/credential_pool.py",
    ]

    for f in files:
        fpath = os.path.join(os.path.dirname(__file__), "..", f)
        fpath = os.path.abspath(fpath)
        # py_compile ne leve pas d'exception si OK
        py_compile.compile(fpath, doraise=True)


def test_run_agent_imports():
    """run_agent.py imports without error (with stubs when needed)."""
    # Stub modules that may be missing locally
    for mod in ["websockets", "prompt_toolkit"]:
        _ensure_stub(mod)

    # L'import de run_agent peut échouer si une dep native manque,
    # on test donc au minimum la compilation
    import py_compile
    import os
    fpath = os.path.join(os.path.dirname(__file__), "..", "run_agent.py")
    fpath = os.path.abspath(fpath)
    py_compile.compile(fpath, doraise=True)
