"""
agent_bridge.py — Adaptateur qui branche le vrai moteur Naabiga (AIAgent)
sur les sessions SSE du backend NaabigaCode.

Pattern repris de naabiga_cli/oneshot.py :
  1. résoudre provider/modèle via resolve_runtime_provider()
  2. construire AIAgent (quiet_mode=True, callbacks d'affichage coupés)
  3. attacher stream_delta_callback → émet {"type":"assistant","text":…}
  4. run_conversation() dans un thread (le moteur est synchrone)
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path
from typing import Any, Callable, Dict, Optional

# ── Bootstrap : le coeur Naabiga vit dans backend/agent + run_agent.py ──
BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

logger = logging.getLogger("naabigacode.bridge")

# Raccourci d'émission SSE (défini dans main.py, injecté par run_turn)
EmitFn = Callable[[Dict[str, Any]], None]


def _resolve_runtime(provider: Optional[str], model: Optional[str]) -> Dict[str, Any]:
    """Résout (provider, base_url, api_key, api_mode) comme le fait oneshot."""
    from naabiga_cli.runtime_provider import resolve_runtime_provider

    runtime = resolve_runtime_provider(
        requested=provider or os.getenv("NAABIGA_INFERENCE_PROVIDER", "").strip() or None,
        target_model=model or None,
    )
    return runtime


def _build_agent(runtime: Dict[str, Any], model: str, emit: EmitFn):
    """Construit AIAgent branché sur les callbacks → SSE."""
    from run_agent import AIAgent

    agent = AIAgent(
        api_key=runtime.get("api_key"),
        base_url=runtime.get("base_url"),
        provider=runtime.get("provider"),
        api_mode=runtime.get("api_mode"),
        model=model,
        quiet_mode=True,
        platform="cli",
        # Streaming → SSE
        stream_delta_callback=lambda delta: _emit_delta(emit, delta),
        # Display callbacks neutralisés (oneshot le fait aussi) : tout passe
        # par stream_delta_callback pour ne pas polluer stdout.
        suppress_status_output=True,
    )
    agent.suppress_status_output = True
    agent.stream_delta_callback = lambda delta: _emit_delta(emit, delta)
    agent.tool_gen_callback = None
    return agent


def _emit_delta(emit: EmitFn, delta: Any) -> None:
    """stream_delta_callback reçoit du texte (str) ou None (fin de turn)."""
    if delta is None:
        return
    text = str(delta)
    if text.strip():
        emit({"type": "assistant", "text": text})


def run_turn(
    session_id: str,
    user_message: str,
    emit: EmitFn,
    provider: Optional[str] = None,
    model: Optional[str] = None,
) -> Dict[str, Any]:
    """Exécute un tour complet du moteur Naabiga. Bloquant → lancer dans un thread.

    Retourne le résultat de run_conversation() (final_response, messages, …).
    """
    # Le moteur Naabiga est verbeux sur stderr : on garde les logs fichiers mais
    # on coupe les logs racine pendant le tour (comme oneshot).
    logging.disable(logging.CRITICAL)
    try:
        from naabiga_cli.config import load_config

        runtime = _resolve_runtime(provider, model)

        # Même résolution que naabiga_cli/oneshot.py : explicite → env → config.
        cfg = load_config()
        model_cfg = cfg.get("model") or {}
        if isinstance(model_cfg, str):
            cfg_model = model_cfg
        else:
            cfg_model = model_cfg.get("default") or model_cfg.get("model") or ""
        env_model = os.getenv("NAABIGA_INFERENCE_MODEL", "").strip()
        effective_model = (model or "").strip() or env_model or cfg_model

        # _run_agent construit l'agent et appelle run_conversation().
        # On lui passe notre callback de streaming via la fermeture ci-dessous.
        result = _run_agent_with_streaming(runtime, effective_model, user_message, emit)
        return result
    except Exception as exc:
        logger.exception("Naabiga turn failed: %s", exc)
        return {"final_response": "", "completed": False, "failed": True, "error": str(exc)}
    finally:
        logging.disable(logging.NOTSET)


def _run_agent_with_streaming(
    runtime: Dict[str, Any], model: str, prompt: str, emit: EmitFn
) -> Dict[str, Any]:
    """Variante de naabiga_cli.oneshot._run_agent avec stream_delta_callback."""
    from naabiga_cli.oneshot import _normalize_toolsets
    from naabiga_cli.config import load_config
    from naabiga_cli.tools_config import _get_platform_tools
    from run_agent import AIAgent

    cfg = load_config()
    toolsets_list = _normalize_toolsets(None)
    if toolsets_list is None:
        toolsets_list = sorted(_get_platform_tools(cfg, "cli"))

    agent = AIAgent(
        api_key=runtime.get("api_key"),
        base_url=runtime.get("base_url"),
        provider=runtime.get("provider"),
        api_mode=runtime.get("api_mode"),
        model=model,
        enabled_toolsets=toolsets_list,
        quiet_mode=True,
        platform="cli",
        stream_delta_callback=lambda delta: _emit_delta(emit, delta),
    )
    agent.suppress_status_output = True
    agent.stream_delta_callback = lambda delta: _emit_delta(emit, delta)
    agent.tool_gen_callback = None

    emit({"type": "info", "message": f"agent Naabiga prêt ({model})"})
    result = agent.run_conversation(prompt)
    return result


async def run_turn_async(
    session_id: str,
    user_message: str,
    emit: EmitFn,
    provider: Optional[str] = None,
    model: Optional[str] = None,
) -> Dict[str, Any]:
    """Wrapper async : exécute le tour dans un thread pour ne pas bloquer uvicorn."""
    return await asyncio.to_thread(
        run_turn, session_id, user_message, emit, provider, model
    )
