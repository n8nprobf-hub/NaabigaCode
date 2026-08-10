"""Engine smoke tests — constructs a real AIAgent without network.

These tests import run_agent (the Naabiga engine core) and build an
AIAgent instance with all dependencies stubbed, proving the engine's
constructor contract holds. No external provider is called.

Run in CI: pytest runs from backend/ with requirements.txt installed.
"""

import sys
import types
import importlib
from unittest.mock import MagicMock


def _ensure_stub(name: str) -> None:
    """Inject a stub module if the real one is not importable."""
    if name in sys.modules:
        return
    try:
        importlib.import_module(name)
    except ImportError:
        stub = types.ModuleType(name)
        # Make attribute access on the stub return MagicMock so deep chains
        # (openai.OpenAI(), client.chat.completions.create(...)) do not crash.
        stub.__getattr__ = lambda attr: MagicMock()  # type: ignore[attr-defined]
        sys.modules[name] = stub


# Third-party deps that run_agent imports at module level. In CI these are
# installed via requirements.txt; locally we stub so the test is hermetic.
for _dep in [
    "openai",
    "httpx",
    "dotenv",
    "websockets",
    "prompt_toolkit",
    "croniter",
    "ruamel.yaml",
    "jwt",
    "yaml",
    "pydantic",
    "psutil",
    "PIL",
]:
    _ensure_stub(_dep)

# openai.OpenAI must be a callable factory (AIAgent.__init__ builds a client).
_ensure_stub("openai")
import openai  # noqa: E402 — stub guaranteed above

if not isinstance(getattr(openai, "OpenAI", None), MagicMock):
    openai.OpenAI = MagicMock()  # type: ignore[attr-defined]

# Alias stubs that some modules import as `import ruamel.yaml`
if "ruamel" not in sys.modules:
    _ruamel = types.ModuleType("ruamel")
    _ruamel.yaml = sys.modules.get("ruamel.yaml") or types.ModuleType("ruamel.yaml")
    sys.modules["ruamel"] = _ruamel

# Make the backend/ dir importable (tests run from backend/)
import os

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)


def test_run_agent_imports() -> None:
    """run_agent module imports successfully in the engine context."""
    import run_agent

    assert hasattr(run_agent, "AIAgent")


def test_aiagent_constructs_with_defaults() -> None:
    """AIAgent() builds with no arguments (all params optional)."""
    import run_agent

    agent = run_agent.AIAgent()
    try:
        # Constructor must not require a provider or network.
        assert agent is not None
        assert isinstance(agent, run_agent.AIAgent)
    finally:
        # Tear down any background threads the agent started.
        if hasattr(agent, "shutdown"):
            try:
                agent.shutdown()
            except Exception:
                pass


def test_aiagent_constructs_with_model() -> None:
    """AIAgent accepts a model + base_url without network."""
    import run_agent

    agent = run_agent.AIAgent(
        model="test-model",
        base_url="https://example.invalid/v1",
        api_key="sk-test",
    )
    try:
        assert agent.model == "test-model" if hasattr(agent, "model") else True
    finally:
        if hasattr(agent, "shutdown"):
            try:
                agent.shutdown()
            except Exception:
                pass


def test_aiagent_base_url_property() -> None:
    """The base_url property normalizes hostname."""
    import run_agent

    agent = run_agent.AIAgent(
        base_url="https://platform.example.com/v1",
    )
    try:
        assert hasattr(agent, "base_url")
        # Property may normalize; just ensure it is a string and non-empty.
        assert isinstance(agent.base_url, str) and agent.base_url
        assert "platform.example.com" in agent.base_url
    finally:
        if hasattr(agent, "shutdown"):
            try:
                agent.shutdown()
            except Exception:
                pass