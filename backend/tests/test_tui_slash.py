"""Tests du dispatcher de commandes slash TUI (backend/tui_slash.py).

Vérifie le contrat de handle_slash :
  - None       → le message part au moteur LLM (prompt normal)
  - "consumed" → commande traitée localement, aucun tour LLM
  - "rerun"    → /retry : rejouer le dernier message utilisateur

Exécution : `cd backend && pytest -q`
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from tui_slash import handle_slash, _last_user_text  # noqa: E402


class StubSession:
    """Mini session compatible avec le contrat attendu par handle_slash.

    Reproduit fidèlement Session réelle : emit() alimente queue ET history
    (les transitoires done/aborted exclus) — c'est la branche history que
    /history et /retry empruntent en production.
    """

    def __init__(self) -> None:
        self.id = "test1234abcd"
        self.created_at = time.time()
        self.queue = []
        self.history = []
        self.busy = False

    def emit(self, ev) -> None:
        if ev.get("type") not in ("done", "aborted"):
            self.history.append(ev)
        self.queue.append(ev)


@pytest.fixture()
def session():
    s = StubSession()
    s.emit({"type": "user", "text": "bonjour, que fais-tu ?"})
    return s


def run(cmd, session):
    return session, handle_slash(session.id, session, cmd, session.emit)


def test_plain_text_goes_to_llm(session):
    _, action = run("bonjour comment ça va ?", session)
    assert action is None


def test_help_consumed_and_emits(session):
    sess, action = run("/help", session)
    assert action == "consumed"
    assert any(e.get("type") == "assistant" for e in sess.queue)


def test_status_consumed(session):
    sess, action = run("/status", session)
    assert action == "consumed"
    assert "test1234abcd" in sess.queue[-1].get("text", "")


def test_clear_emits_clear_event(session):
    sess, action = run("/clear", session)
    assert action == "consumed"
    assert any(e.get("type") == "clear" for e in sess.queue)


def test_history_contains_previous_user_message(session):
    sess, action = run("/history", session)
    assert action == "consumed"
    assert any("bonjour" in e.get("text", "") for e in sess.queue)


def test_retry_with_history_reruns(session):
    _, action = run("/retry", session)
    assert action == "rerun"


def test_retry_without_history_consumed():
    fresh = StubSession()
    action = handle_slash(fresh.id, fresh, "/retry", fresh.emit)
    assert action == "consumed"


def test_sessions_consumed(session):
    sess, action = run("/sessions", session)
    assert action == "consumed"
    assert "test1234abcd" in sess.queue[-1].get("text", "")


def test_title_consumed(session):
    sess, action = run("/title ma-session", session)
    assert action == "consumed"
    assert "ma-session" in sess.queue[-1].get("text", "")


def test_title_without_arg_consumed(session):
    _, action = run("/title", session)
    assert action == "consumed"


def test_known_but_not_available_in_tui(session):
    """/memory est connu du registre mais non-TUI → consumé avec message d'info."""
    sess, action = run("/memory", session)
    assert action == "consumed"
    # Vérifie qu'un message est émis (pas envoyé au LLM)
    # Le premier élément est l'user message du fixture, le second est la réponse du handler
    assert len(sess.queue) >= 2
    assert sess.queue[-1].get("type") in ("assistant", "info")


def test_skills_now_implemented_in_tui(session):
    """/skills est maintenant implémenté dans la TUI → consumé avec l'aide."""
    sess, action = run("/skills", session)
    assert action == "consumed"
    # L'aide skills contient les sous-commandes
    assert any("Compétences (skills)" in e.get("text", "") for e in sess.queue)


def test_gateway_now_implemented_in_tui(session):
    """/gateway est maintenant implémenté dans la TUI → consumé avec l'info."""
    sess, action = run("/gateway", session)
    assert action == "consumed"
    assert any("Gateway NaabigaCode" in e.get("text", "") for e in sess.queue)


def test_unknown_command_falls_back_to_llm(session):
    """Commande inconnue → None (le LLM la traite) + info émise."""
    sess, action = run("/xyz-inconnue", session)
    assert action is None
    assert any(e.get("type") == "info" for e in sess.queue)


def test_new_consumed(session):
    _, action = run("/new", session)
    assert action == "consumed"


def test_reset_alias_consumed(session):
    _, action = run("/reset", session)
    assert action == "consumed"


def test_last_user_text_helper():
    s = StubSession()
    s.emit({"type": "user", "text": "dernier"})
    s.emit({"type": "assistant", "text": "réponse"})
    assert _last_user_text(s) == "dernier"


def test_last_user_text_skips_command_marked():
    """Les événements user marqués command (slash consumée) sont ignorés."""
    s = StubSession()
    s.history.append({"type": "user", "text": "vrai message"})
    s.history.append({"type": "user", "text": "/help", "command": True})
    assert _last_user_text(s) == "vrai message"


def test_retry_after_slash_command_targets_real_message():
    """/retry après /help (command marquée) rejoue le DERNIER VRAI message.

    Régression du fix 1686ef1 : /retry cherchait le dernier user de
    l'historique sans exclure les commandes slash consumées — /help puis
    /retry rejouait «/help» comme prompt LLM.
    """
    s = StubSession()
    s.history.append({"type": "user", "text": "explique le projet"})
    s.history.append({"type": "assistant", "text": "réponse 1"})
    s.history.append({"type": "user", "text": "/help", "command": True})
    s.history.append({"type": "assistant", "text": "aide affichée"})
    assert _last_user_text(s, exclude="/retry") == "explique le projet"