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
    "skills",
    "platforms",
}

# Commandes connues du registre mais non exécutables dans la TUI — on le
# dit poliment au lieu de les envoyer au LLM.
_NOT_AVAILABLE_TUI = {
    "skill", "memory", "undo", "redraw", "prompt", "compose",
    "handoff", "branch", "fork", "background", "bg", "btw", "steer",
    "queue", "goal", "subgoal", "moa", "snapshot", "snap", "rollback",
    "approve", "deny", "start", "topic", "sethome",
    "plugins", "tools", "bundles", "pet", "suggestions",
    "reload-skills", "journey", "learning", "save",
    "toolsets",
}


def _stable_history(session: Any) -> List[Dict[str, Any]]:
    """Événements stables de la session (replay exclut les commandes slash)."""
    events: List[Dict[str, Any]] = []
    for ev in getattr(session, "history", []) or []:
        if isinstance(ev, dict) and ev.get("type") == "user" and ev.get("command"):
            # Saute les commandes slash : on ne rejoue que le vrai prompt.
            continue
        events.append(ev)
    return events


def _last_user_text(session: Any, exclude: Optional[str] = None) -> Optional[str]:
    """Dernier message utilisateur réel (hors commandes slash marquées)."""
    for ev in reversed(getattr(session, "history", []) or []):
        if isinstance(ev, dict) and ev.get("type") == "user" and not ev.get("command"):
            if exclude and ev.get("text") == exclude:
                continue
            return ev.get("text")
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
        emit(
            {
                "type": "info",
                "message": f"/{first} inconnue — sera traitée par le LLM.",
            }
        )
        return None

    name = cmd.name

    # Commandes non disponibles dans la TUI (mais reconnues) : on prévient.
    if name in _NOT_AVAILABLE_TUI:
        emit(
            {
                "type": "info",
                "message": f"/{name} n'est pas encore disponible dans la TUI (utilisez le CLI complet naabiga --cli).",
            }
        )
        return "consumed"

    if name == "help":
        lines = ["Commandes disponibles dans la TUI (session) :", ""]
        for category, cmds in _help_by_category().items():
            lines.append(f"  {category} :")
            for c in cmds:
                lines.append(f"    {c}")
            lines.append("")
        emit({"type": "assistant", "text": "\n".join(lines).rstrip()})
        return "consumed"

    if name == "status":
        emit(
            {
                "type": "assistant",
                "text": (
                    f"session : {session_id}\n"
                    f"backend : http://127.0.0.1:8400\n"
                    f"historique : {len(getattr(session, 'history', []) or [])} événements"
                ),
            }
        )
        return "consumed"

    if name == "clear":
        emit({"type": "clear"})
        return "consumed"

    if name == "history":
        hist = _stable_history(session)
        if not hist:
            emit({"type": "assistant", "text": "(historique vide)"})
            return "consumed"
        out = []
        for ev in hist[-20:]:
            t = ev.get("type")
            if t == "user":
                out.append(f"vous : {ev.get('text', '')}")
            elif t == "assistant":
                out.append(f"naabiga : {ev.get('text', '')[:200]}")
        emit({"type": "assistant", "text": "\n".join(out)})
        return "consumed"

    if name == "retry":
        last = _last_user_text(session, exclude=user_message)
        if not last:
            emit({"type": "info", "message": "aucun message à rejouer."})
            return "consumed"
        emit({"type": "info", "message": f"rejoue : {last}"})
        # On ré-émet le dernier vrai message comme prompt LLM.
        # IMPORTANT : on le marque comme commande pour que _run_turn ne le
        # prenne pas pour un vrai message utilisateur à rejouer (sinon boucle
        # infinie : /retry rejoue /retry rejoue /retry…).
        emit({"type": "user", "text": last, "command": True})
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
                    "Nouvelle session : utilisez /clear pour repartir de zéro "
                    "ou relancez la TUI (naabiga) pour une session neuve."
                ),
            }
        )
        return "consumed"

    if name == "skills":
        emit(
            {
                "type": "assistant",
                "text": (
                    "Compétences (skills) :\n"
                    "  /skills search <query>   — rechercher des compétences\n"
                    "  /skills browse           — parcourir le catalogue\n"
                    "  /skills inspect <name>   — détails d'une compétence\n"
                    "  /skills install <name>   — installer une compétence\n"
                    "  /skills audit            — auditer les compétences installées\n"
                    "  /skills pending          — voir les validations en attente\n"
                    "  /skills approve <id>     — approuver une écriture\n"
                    "  /skills reject <id>      — rejeter une écriture\n"
                    "  /skills approval on|off  — basculer la porte d'approbation\n"
                    "\n"
                    "Note : l'installation/validation nécessite le CLI complet (naabiga --cli).\n"
                    "La TUI peut rechercher et inspecter."
                ),
            }
        )
        return "consumed"

    if name == "platforms":
        # Affiche le statut gateway / info (alias gateway)
        emit(
            {
                "type": "assistant",
                "text": (
                    "Gateway NaabigaCode :\n"
                    "  Statut : non connecté (TUI locale)\n"
                    "  Pour connecter le gateway : naabiga --gateway\n"
                    "\n"
                    "Commandes gateway disponibles (CLI/gateway) :\n"
                    "  /start     — accusé de réception de démarrage de plateforme\n"
                    "  /approve   — approuver une commande en attente\n"
                    "  /deny      — refuser une commande en attente\n"
                    "  /sethome   — définir ce chat comme canal d'accueil\n"
                    "  /topic     — sessions par sujet Telegram\n"
                    "\n"
                    "Le gateway gère Telegram, Discord, Slack, Matrix, etc.\n"
                    "Depuis la TUI : utilisez /help pour la liste complète."
                ),
            }
        )
        return "consumed"

    # Commande inconnue ou non gérée ici → laisser partir au LLM.
    return None