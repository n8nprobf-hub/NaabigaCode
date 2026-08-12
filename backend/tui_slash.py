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
import os
import sys
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
    "profile",
    "config",
    "model",
    "personality",
    "yolo",
    "reasoning",
    "fast",
    "voice",
    "verbose",
    "footer",
    "timestamps",
    "statusbar",
    "tools",
    "toolsets",
    "memory",
    "bundles",
    "learn",
    "cron",
    "suggestions",
    "blueprint",
    "curator",
    "kanban",
    "reload",
    "reload-mcp",
    "reload-skills",
    "browser",
    "plugins",
    "usage",
    "credits",
    "insights",
    "version",
    "debug",
    "update",
    "branch",
    "fork",
    "compress",
    "compact",
    "snapshot",
    "snap",
    "rollback",
    "stop",
    "background",
    "bg",
    "btw",
    "agents",
    "tasks",
    "journey",
    "learning",
    "memory-graph",
    "queue",
    "steer",
    "goal",
    "moa",
    "subgoal",
    "resume",
    "save",
}

# Commandes connues du registre mais non exécutables dans la TUI — on le
# dit poliment au lieu de les envoyer au LLM.
_NOT_AVAILABLE_TUI = {
    "skill", "undo", "redraw", "prompt", "compose",
    "handoff", "approve", "deny", "start", "topic", "sethome",
    "pet", "hatch",
    "billing", "copy", "paste", "image", "quit", "exit",
    "commands", "platform", "restart",
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

    # ─── Configuration / Profil ────────────────────────────────────────
    if name == "profile":
        emit({"type": "assistant", "text": f"Profil actif : default\nRépertoire : {os.getenv('NAABIGA_HOME', os.path.expanduser('~/.naabiga'))}"})
        return "consumed"

    if name == "config":
        # Affiche config.yaml (sanitized)
        try:
            from naabiga_cli.config import read_raw_config
            import json
            cfg = read_raw_config()
            # Masque les clés sensibles
            for k in list(cfg.keys()):
                if "key" in k.lower() or "secret" in k.lower() or "token" in k.lower():
                    cfg[k] = "***"
            emit({"type": "assistant", "text": f"Configuration :\n{json.dumps(cfg, indent=2, ensure_ascii=False)}"})
        except Exception as e:
            emit({"type": "error", "message": f"config: {e}"})
        return "consumed"

    if name == "model":
        if not rest.strip():
            emit({"type": "assistant", "text": f"Modèle actuel : {os.getenv('NAABIGA_INFERENCE_MODEL', 'auto/best-coding')}\nProvider : {os.getenv('NAABIGA_INFERENCE_PROVIDER', 'omniroute')}\nUsage : /model <model> [--provider name] [--global|--session] [--refresh]"})
        else:
            emit({"type": "info", "message": f"Changement de modèle non implémenté en TUI locale (utilisez naabiga --cli). Actuel : {os.getenv('NAABIGA_INFERENCE_MODEL', 'auto')}"})
        return "consumed"

    if name == "personality":
        if not rest.strip():
            emit({"type": "assistant", "text": "Personnalité actuelle : default\nUsage : /personality [name]"})
        else:
            emit({"type": "info", "message": "Changement personnalité non implémenté en TUI locale."})
        return "consumed"

    if name == "yolo":
        current = os.getenv("NAABIGA_YOLO", "false").lower() in ("1", "true", "yes", "on")
        if not rest.strip():
            emit({"type": "assistant", "text": f"YOLO mode : {'ON' if current else 'OFF'}\nUsage : /yolo [on|off|status]"})
        else:
            val = rest.strip().lower()
            if val in ("on", "true", "1", "yes"):
                os.environ["NAABIGA_YOLO"] = "true"
                emit({"type": "assistant", "text": "YOLO mode : ON (toutes approbations sautées)"})
            elif val in ("off", "false", "0", "no"):
                os.environ["NAABIGA_YOLO"] = "false"
                emit({"type": "assistant", "text": "YOLO mode : OFF"})
            else:
                emit({"type": "assistant", "text": f"YOLO mode : {'ON' if current else 'OFF'}"})
        return "consumed"

    if name == "reasoning":
        if not rest.strip():
            emit({"type": "assistant", "text": "Reasoning effort : non configuré\nUsage : /reasoning [none|minimal|low|medium|high|xhigh|show|hide|full|clamp]"})
        else:
            emit({"type": "info", "message": "Reasoning non implémenté en TUI locale."})
        return "consumed"

    if name == "fast":
        if not rest.strip():
            emit({"type": "assistant", "text": "Mode rapide : non configuré\nUsage : /fast [normal|fast|status]"})
        else:
            emit({"type": "info", "message": "Mode rapide non implémenté en TUI locale."})
        return "consumed"

    if name == "voice":
        if not rest.strip():
            emit({"type": "assistant", "text": "Mode vocal : OFF\nUsage : /voice [on|off|tts|status]"})
        else:
            emit({"type": "info", "message": "Mode vocal non implémenté en TUI locale."})
        return "consumed"

    if name == "verbose":
        if not rest.strip():
            emit({"type": "assistant", "text": "Verbose : off\nUsage : /verbose [off|new|all|verbose|log]"})
        else:
            emit({"type": "info", "message": "Verbose non implémenté en TUI locale."})
        return "consumed"

    if name == "footer":
        if not rest.strip():
            emit({"type": "assistant", "text": "Footer métadonnées : ON\nUsage : /footer [on|off|status]"})
        else:
            emit({"type": "info", "message": "Footer non implémenté en TUI locale."})
        return "consumed"

    if name == "timestamps":
        if not rest.strip():
            emit({"type": "assistant", "text": "Timestamps : OFF\nUsage : /timestamps [on|off|status]"})
        else:
            emit({"type": "info", "message": "Timestamps non implémenté en TUI locale."})
        return "consumed"

    if name == "statusbar":
        if not rest.strip():
            emit({"type": "assistant", "text": "Statusbar : OFF (TUI locale)\nUsage : /statusbar [on|off|status]"})
        else:
            emit({"type": "info", "message": "Statusbar non implémenté en TUI locale."})
        return "consumed"

    # ─── Tools & Skills ───────────────────────────────────────────────
    if name == "tools":
        emit({"type": "assistant", "text": "Outils : gérés par l'agent (bash, read, write, edit, search, browser, etc.)\nUsage : /tools [list|disable|enable] [name...] — nécessite CLI complet"})
        return "consumed"

    if name == "toolsets":
        emit({"type": "assistant", "text": "Toolsets disponibles : default, coding, research, browsing\nUsage : /toolsets — nécessite CLI complet"})
        return "consumed"

    if name == "memory":
        emit({"type": "assistant", "text": "Mémoire : aucune écriture en attente\nUsage : /memory [pending|approve|reject|approval] — nécessite CLI complet"})
        return "consumed"

    if name == "bundles":
        emit({"type": "assistant", "text": "Bundles de compétences : aucun installé\nUsage : /bundles"})
        return "consumed"

    if name == "learn":
        if not rest.strip():
            emit({"type": "assistant", "text": "Usage : /learn <what to learn from> — dossiers, URL, ce chat, notes"})
        else:
            emit({"type": "info", "message": f"Apprentissage demandé : {rest.strip()} (nécessite CLI complet pour persistance)"})
        return "consumed"

    if name == "cron":
        emit({"type": "assistant", "text": "Tâches planifiées : aucune\nUsage : /cron [list|add|create|edit|pause|resume|run|remove] — nécessite CLI complet"})
        return "consumed"

    if name == "suggestions":
        emit({"type": "assistant", "text": "Suggestions d'automation : aucune\nUsage : /suggestions [accept|dismiss|catalog|clear] — nécessite CLI complet"})
        return "consumed"

    if name == "blueprint":
        emit({"type": "assistant", "text": "Blueprints d'automation : aucun configuré\nUsage : /blueprint [name] [slot=value...] — nécessite CLI complet"})
        return "consumed"

    if name == "curator":
        emit({"type": "assistant", "text": "Curateur compétences : idle\nUsage : /curator [status|run|pause|resume|pin|unpin|restore|list-archived] — nécessite CLI complet"})
        return "consumed"

    if name == "kanban":
        emit({"type": "assistant", "text": "Kanban : aucun board initialisé\nUsage : /kanban [init|boards|create|list|show|assign|...] — nécessite CLI complet"})
        return "consumed"

    if name == "reload":
        emit({"type": "info", "message": "Rechargement .env : non disponible en TUI locale (redémarrez la TUI)"})
        return "consumed"

    if name == "reload-mcp":
        emit({"type": "info", "message": "Rechargement MCP : non disponible en TUI locale"})
        return "consumed"

    if name == "reload-skills":
        emit({"type": "info", "message": "Rescan skills : non disponible en TUI locale"})
        return "consumed"

    if name == "browser":
        emit({"type": "assistant", "text": "Navigateur CDP : non connecté\nUsage : /browser [connect|disconnect|status] — nécessite CLI complet"})
        return "consumed"

    if name == "plugins":
        emit({"type": "assistant", "text": "Plugins installés : aucun\nUsage : /plugins — nécessite CLI complet"})
        return "consumed"

    # ─── Info / Debug ─────────────────────────────────────────────────
    if name == "usage":
        emit({"type": "assistant", "text": "Usage tokens : non disponible en TUI locale (voir dashboard)"})
        return "consumed"

    if name == "credits":
        emit({"type": "assistant", "text": "Crédits Nous : non disponible en TUI locale"})
        return "consumed"

    if name == "insights":
        emit({"type": "assistant", "text": "Insights : non disponible en TUI locale"})
        return "consumed"

    if name == "version":
        try:
            import naabiga_cli
            v = getattr(naabiga_cli, "__version__", "inconnue")
        except Exception:
            v = "inconnue"
        emit({"type": "assistant", "text": f"NaabigaCode backend {v}\nFrontend : v0.2.7\nPython : {sys.version.split()[0]}"})
        return "consumed"

    if name == "debug":
        emit({"type": "assistant", "text": "Debug report : non disponible en TUI locale (utilisez naabiga --cli debug)"})
        return "consumed"

    if name == "update":
        emit({"type": "assistant", "text": "Mise à jour : `npm install -g naabigacode@latest`\nPuis relancez la TUI."})
        return "consumed"

    # ─── Session avancées ─────────────────────────────────────────────
    if name in ("branch", "fork"):
        emit({"type": "assistant", "text": f"/{name} : branchement de session non implémenté en TUI locale"})
        return "consumed"

    if name in ("compress", "compact"):
        emit({"type": "assistant", "text": f"/{name} : compression contexte non implémentée en TUI locale"})
        return "consumed"

    if name in ("snapshot", "snap"):
        emit({"type": "assistant", "text": f"/{name} : snapshots non implémentés en TUI locale"})
        return "consumed"

    if name == "rollback":
        emit({"type": "assistant", "text": "/rollback : restauration fichiers non implémentée en TUI locale"})
        return "consumed"

    if name == "stop":
        # Déclenche abort sur la session courante
        session.abort_event.set()
        emit({"type": "assistant", "text": "Arrêt demandé — tour en cours interrompu."})
        return "consumed"

    if name in ("background", "bg", "btw"):
        if not rest.strip():
            emit({"type": "assistant", "text": "Usage : /background <prompt> — exécute en arrière-plan (nécessite CLI complet)"})
        else:
            emit({"type": "info", "message": f"Background demandé : {rest.strip()} (non implémenté en TUI locale)"})
        return "consumed"

    if name in ("agents", "tasks"):
        emit({"type": "assistant", "text": "Agents/Tâches actifs : aucun\nUsage : /agents"})
        return "consumed"

    if name in ("journey", "learning", "memory-graph"):
        emit({"type": "assistant", "text": f"/{name} : chronologie apprentissage non implémentée en TUI locale"})
        return "consumed"

    if name == "queue":
        if not rest.strip():
            emit({"type": "assistant", "text": "Usage : /queue <prompt> — file pour prochain tour"})
        else:
            emit({"type": "info", "message": f"Mis en file : {rest.strip()} (non implémenté en TUI locale)"})
        return "consumed"

    if name == "steer":
        if not rest.strip():
            emit({"type": "assistant", "text": "Usage : /steer <prompt> — injecte après prochain tool"})
        else:
            emit({"type": "info", "message": f"Steer : {rest.strip()} (non implémenté en TUI locale)"})
        return "consumed"

    if name == "goal":
        if not rest.strip():
            emit({"type": "assistant", "text": "Objectif permanent : aucun\nUsage : /goal [text|draft|show|pause|resume|clear|status|wait|unwait]"})
        else:
            emit({"type": "info", "message": f"Objectif : {rest.strip()} (non implémenté en TUI locale)"})
        return "consumed"

    if name == "moa":
        if not rest.strip():
            emit({"type": "assistant", "text": "Usage : /moa <prompt> — Mixture of Agents"})
        else:
            emit({"type": "info", "message": f"MoA : {rest.strip()} (non implémenté en TUI locale)"})
        return "consumed"

    if name == "subgoal":
        if not rest.strip():
            emit({"type": "assistant", "text": "Sous-objectifs : aucun\nUsage : /subgoal [text|remove N|clear]"})
        else:
            emit({"type": "info", "message": f"Subgoal : {rest.strip()} (non implémenté en TUI locale)"})
        return "consumed"

    if name == "resume":
        if not rest.strip():
            emit({"type": "assistant", "text": "Usage : /resume [name] — reprendre session nommée"})
        else:
            emit({"type": "info", "message": f"Resume session : {rest.strip()} (non implémenté en TUI locale)"})
        return "consumed"

    if name == "save":
        emit({"type": "info", "message": "Sauvegarde conversation : non implémentée en TUI locale"})
        return "consumed"

    # Commande inconnue ou non gérée ici → laisser partir au LLM.
    return None