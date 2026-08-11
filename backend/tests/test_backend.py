"""Smoke tests du backend NaabigaCode.

Ces tests vérifient le contrat HTTP/SSE du backend sans appeler de LLM :
le module `agent_bridge` est remplacé par un stub qui émet un événement
assistant puis retourne une réponse finale, ce qui couvre le chemin complet
session → message → événements → done.

Lancement :  `cd backend && pytest -q`
"""

from __future__ import annotations

import importlib
import sys
import time
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


class StubAgentBridge:
    """Fake agent_bridge : répond un message fixe sans aucun appel réseau."""

    async def run_turn_async(self, session_id, user_message, emit, **kwargs):
        emit({"type": "assistant", "text": f"re: {user_message}"})
        return {
            "final_response": f"re: {user_message}",
            "streamed": True,
            "failed": False,
        }


@pytest.fixture()
def client(monkeypatch):
    # Remplace le vrai pont par le stub AVANT d'importer main,
    # afin que `from agent_bridge import run_turn_async` résolve le stub.
    monkeypatch.setitem(sys.modules, "agent_bridge", StubAgentBridge())

    module = importlib.import_module("main")
    module.sessions.clear()  # départ propre entre tests

    from fastapi.testclient import TestClient

    with TestClient(module.app) as c:
        yield c


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_create_session(client):
    r = client.post("/session/create")
    assert r.status_code == 200
    data = r.json()
    assert "session_id" in data
    assert len(data["session_id"]) == 12  # uuid4().hex[:12]


def test_message_unknown_session(client):
    r = client.post("/session/nope/message", json={"message": "hello"})
    assert r.status_code == 200
    assert r.json() == {"accepted": False}


def test_message_empty(client):
    sid = client.post("/session/create").json()["session_id"]
    r = client.post(f"/session/{sid}/message", json={"message": "   "})
    assert r.json() == {"accepted": False}


def test_abort(client):
    r = client.post("/session/unknown/abort")
    assert r.json() == {"aborted": False}

    sid = client.post("/session/create").json()["session_id"]
    r = client.post(f"/session/{sid}/abort")
    assert r.json() == {"aborted": True}


def test_events_not_found(client):
    r = client.get("/session/unknown/events")
    assert r.status_code == 200
    assert "session not found" in r.text


def test_full_turn_streams_events(client):
    """Tour complet : message → événements user/assistant/done, via le stub."""
    sid = client.post("/session/create").json()["session_id"]

    r = client.post(f"/session/{sid}/message", json={"message": "bonjour"})
    assert r.json() == {"accepted": True}

    module = importlib.import_module("main")
    session = module.sessions[sid]

    # Attend que le tour soit terminé : événement "done" émis ET busy repassé
    # à False (le finally de _run_turn fait busy=False juste après "done").
    deadline = time.time() + 5
    while time.time() < deadline:
        done = any(e.get("type") == "done" for e in session.queue)
        if done and not session.busy:
            break
        time.sleep(0.02)

    types = {e.get("type") for e in session.queue}
    assert "user" in types
    assert "assistant" in types
    assert "done" in types
    assert session.busy is False


def test_session_busy_rejects_second_message(client):
    sid = client.post("/session/create").json()["session_id"]

    module = importlib.import_module("main")
    session = module.sessions[sid]
    session.busy = True
    r = client.post(f"/session/{sid}/message", json={"message": "autre"})
    assert r.json() == {"accepted": False}
    assert any(e.get("type") == "error" for e in session.queue)


def test_history_replays_stable_events(client):
    """/history renvoie les événements stables même après consommation SSE."""
    sid = client.post("/session/create").json()["session_id"]
    client.post(f"/session/{sid}/message", json={"message": "bonjour"})

    module = importlib.import_module("main")
    session = module.sessions[sid]
    deadline = time.time() + 5
    while time.time() < deadline:
        done = any(e.get("type") == "done" for e in session.queue)
        if done and not session.busy:
            break
        time.sleep(0.02)

    # Simule la consommation par un TUI déjà connecté au SSE
    session.queue.clear()

    r = client.get(f"/session/{sid}/history")
    assert r.status_code == 200
    events = r.json()["events"]
    types = [e.get("type") for e in events]
    assert "user" in types
    assert "assistant" in types
    assert "done" not in types
    assert "aborted" not in types


def test_history_unknown_session(client):
    r = client.get("/session/nope/history")
    assert r.status_code == 200
    assert r.json() == {"events": []}


def test_purge_expired_sessions(client):
    """La purge supprime les sessions inactives mais pas les actives."""
    module = importlib.import_module("main")
    sid_old = client.post("/session/create").json()["session_id"]
    sid_fresh = client.post("/session/create").json()["session_id"]

    # Vieillit artificiellement la première session
    module.sessions[sid_old].last_active = time.time() - module.SESSION_TTL_SECONDS - 10
    module.sessions[sid_old].busy = False

    # Exerce le VRAI chemin de purge (fonction partagée avec la boucle)
    purged = module.purge_expired_sessions()

    assert purged == 1
    assert sid_old not in module.sessions
    assert sid_fresh in module.sessions


def test_slash_help_consumed_without_llm(client):
    """Le dispatch /help est intercepté AVANT le tour LLM.

    Le stub agent_bridge répondrait "re: /help" ; le fait que la réponse
    contienne le menu de commandes prouve que le LLM n'a pas été appelé.
    """
    sid = client.post("/session/create").json()["session_id"]

    r = client.post(f"/session/{sid}/message", json={"message": "/help"})
    assert r.json() == {"accepted": True}

    module = importlib.import_module("main")
    session = module.sessions[sid]
    deadline = time.time() + 5
    while not any(e.get("type") == "done" for e in session.queue) and time.time() < deadline:
        time.sleep(0.02)

    types = {e.get("type") for e in session.queue}
    assert "user" in types
    assert "done" in types

    assistant = [e.get("text", "") for e in session.queue if e.get("type") == "assistant"]
    assert any("Commandes disponibles" in t for t in assistant), assistant


def test_slash_unknown_falls_back_to_llm(client):
    """Une commande inconnue retombe sur le tour LLM (stub appelé)."""
    sid = client.post("/session/create").json()["session_id"]

    r = client.post(f"/session/{sid}/message", json={"message": "/xyz-commande"})
    assert r.json() == {"accepted": True}

    module = importlib.import_module("main")
    session = module.sessions[sid]
    deadline = time.time() + 5
    while not any(e.get("type") == "done" for e in session.queue) and time.time() < deadline:
        time.sleep(0.02)

    # Le stub répond "re: <texte>" — preuve que le LLM (stub) a tourné.
    assistant = [e.get("text", "") for e in session.queue if e.get("type") == "assistant"]
    assert any("re:" in t for t in assistant), assistant