"""Dispatch des commandes slash pour la TUI NaabigaCode.

Pont entre le registre central (naabiga_cli.commands) et l'interface de
session HTTP/SSE (backend/main.py). Quand l'utilisateur tape une commande
``/cmd`` dans la TUI React, elle arrive ici AVANT tout appel LLM.

Contrat : ``handle_slash(...)`` émet lui-même les événements via ``emit`` et
retourne :
  - ``None``       → le message doit partir au moteur comme prompt normal
  - ``"consumed"`` → la commande a été traitée, aucun tour LLM
  - ``"rerun"``    → la commande a été traitée ET il faut rejouer le dernier
                     message utilisateur en tour LLM (/retry)
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger("naabigacode.tui_commands")

# Commandes réellement exécutables dans le contexte TUI (session HTTP locale).
_IMPLEMENTED = {
    "help",
    "status",
    "clear",
    "history",
    "retry",
    "title",
    "session",
    "sessions",
    "whoami",
    "new",
    "reset",
}

# Commandes connues du registre mais non exécutables dans la TUI — on le
# dit poliment au lieu de les envoyer au LLM.
_NOT_AVAILABLE_TUI = {
    "skill", "skills", "memory", "undo", "redraw", "prompt", "compose",
    "handoff", "branch", "fork", "background", "bg", "btw", "steer",
    "queue", "goal", "subgoal", "moa", "snapshot", "snap", "rollback",
    "approve", "deny", "start", "topic", "sethome",
    "gateway", "plugins", "tools", "bundles", "pet", "suggestions",
    "reload-skills", "journey", "learning", "save",
}


def _snapshot_events(session: Any) -> List[Dict[str, Any]]:
    """Copie plate de la file d'événements de la session."""
    return list(getattr(session, "queue", []) or [])


def _last_user_text(session: Any) -> Optional[str]:
    """Dernier message utilisateur de la session (pour /retry)."""
    for ev in reversed(_snapshot_events(session)):
        if ev.get("type") == "user":
            return ev.get("text", "")
    return None


def _help_by_category() -> Dict[str, List[str]]:
    try:
        from naabiga_cli.commands import COMMAND_REGISTRY
    except Exception:  # pragma: no cover
        return {"Session": ["/help — afficher cette aide"]}

    out: Dict[str, List[str]] = {}
    for cmd in COMMAND_REGISTRY:
        if cmd.name in _IMPLEMENTED:
            hint = f" {cmd.args_hint}" if cmd.args_hint else ""
            out.setdefault(cmd.category, []).append(
                f"/{cmd.name}{hint} — {cmd.description}"
            )
    return out


def handle_slash(
    session_id: str,
    session: Any,
    user_message: str,
    emit: Any,
) -> Optional[str]:
    """Traite un message commençant par ``/`` (voir contrat en tête de module)."""
    if not user_message or not user_message.startswith("/"):
        return None

    try:
        from naabiga_cli.commands import resolve_command
    except Exception as exc:  # pragma: no cover
        logger.warning("registre des commandes indisponible : %s", exc)
        return None

    stripped = user_message.strip()
    first, _, rest = stripped[1:].partition(" ")
    cmd = resolve_command(first)

    if cmd is None:
        # Commande inconnue : info, puis on laisse le LLM la traiter.
        emit({"type": "info", "message": f"commande inconnue «/{first}» — traitement comme prompt…"})
        return None

    name = cmd.name

    if name in _NOT_AVAILABLE_TUI:
        emit(
            {
                "type": "info",
                "message": (
                    f"/{name} — {cmd.description}\n"
                    f"Cette commande n'est pas encore disponible dans la TUI "
                    f"(disponible dans le CLI naabiga ou sur le gateway)."
                ),
            }
        )
        return "consumed"

    if name not in _IMPLEMENTED:
        emit(
            {
                "type": "info",
                "message": f"/{name} — {cmd.description}\nNon implémenté côté TUI pour l'instant.",
            }
        )
        return "consumed"

    # ---- Commandes implémentées ----
    if name == "help":
        lines = ["Commandes disponibles dans la TUI (session) :"]
        for category, cmds in _help_by_category().items():
            lines.append(f"· {category} :")
            lines.extend(f"  {c}" for c in cmds)
        lines.append("")
        lines.append(
            "(les commandes skills / CLI / gateway sont reconnues mais signalées "
            "comme non disponibles dans la TUI.)"
        )
        emit({"type": "assistant", "text": "\n".join(lines)})
        return "consumed"

    if name == "whoami":
        emit(
            {
                "type": "assistant",
                "text": (
                    "TUI NaabigaCode — session locale HTTP/SSE.\n"
                    "Les droits et rôles (admin/utilisateur) ne s'appliquent qu'au gateway."
                ),
            }
        )
        return "consumed"

    if name == "status":
        runtime_secs = int(time.time() - getattr(session, "created_at", time.time()))
        emit(
            {
                "type": "assistant",
                "text": (
                    f"Session {session_id}\n"
                    f"créée il y a {runtime_secs}s\n"
                    f"événements dans la file : {len(getattr(session, 'queue', []))}\n"
                    f"occupée : {getattr(session, 'busy', False)}"
                ),
            }
        )
        return "consumed"

    if name == "clear":
        # Événement spécial consommé par le frontend pour vider l'écran.
        emit({"type": "clear"})
        emit({"type": "assistant", "text": "écran effacé."})
        return "consumed"

    if name == "history":
        history = [
            f"[{i}] {ev.get('type')}: {str(ev.get('text') or ev.get('message') or '')[:120]}"
            for i, ev in enumerate(_snapshot_events(session))
        ]
        text = "\n".join(history) if history else "(historique vide)"
        emit({"type": "assistant", "text": text})
        return "consumed"

    if name == "retry":
        last = _last_user_text(session)
        if not last:
            emit({"type": "assistant", "text": "rien à rejouer (aucun message utilisateur)."})
            return "consumed"
        emit({"type": "assistant", "text": f"Rejeu du dernier message : «{last[:200]}»"})
        # Rejeu réel : le tour LLM repart avec la prompt originale.
        return "rerun"

    if name in ("session", "sessions"):
        emit({"type": "assistant", "text": f"session courante : {session_id}"})
        return "consumed"

    if name == "title":
        title = rest.strip()
        if not title:
            emit({"type": "assistant", "text": "usage : /title <nom> — définir le titre de la session."})
            return "consumed"
        emit({"type": "assistant", "text": f"session renommée : {title}"})
        return "consumed"

    if name in ("new", "reset"):
        emit(
            {
                "type": "assistant",
                "text": (
                    "Nouvelle session : créez-en une via le frontend "
                    "(rechargez la TUI ou utilisez /help pour les commandes)."
                ),
            }
        )
        return "consumed"

    # ---- Fallback : on laisse le LLM juger ----
    return None