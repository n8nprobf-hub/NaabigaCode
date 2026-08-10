"""
NaabigaCode Backend — Python agent core served over FastAPI + SSE.
Replaces the curses TUI layer with a React/Ink frontend.

Session contract:
  POST /session/create         → { session_id }
  POST /session/{id}/message   → { accepted: bool }
  GET  /session/{id}/events    → SSE stream of event dicts
  POST /session/{id}/abort     → { aborted: bool }
  GET  /health                 → { status }
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time
import uuid
from collections import deque
from pathlib import Path
from typing import Any, AsyncGenerator, Deque, Dict

import uvicorn
from fastapi import FastAPI
from fastapi.responses import StreamingResponse

# ── Path bootstrap so backend/ is a package root ──────────────────────
BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("naabigacode.backend")

# ── In-memory session store (MVP) ────────────────────────────────────
SESSION_TTL_SECONDS = 3600  # 1h d'inactivité max avant purge


class Session:
    def __init__(self, session_id: str) -> None:
        self.id = session_id
        self.created_at = time.time()
        self.last_active = time.time()
        self.queue: Deque[Dict[str, Any]] = deque()
        self.abort_event = asyncio.Event()
        self.busy = False

    def touch(self) -> None:
        self.last_active = time.time()

    @property
    def expired(self) -> bool:
        return (time.time() - self.last_active) > SESSION_TTL_SECONDS

    def emit(self, event: Dict[str, Any]) -> None:
        self.touch()
        self.queue.append(event)

    async def stream_events(self) -> AsyncGenerator[str, None]:
        """Yield SSE-formatted events until abort or close."""
        try:
            while True:
                if self.abort_event.is_set():
                    self.abort_event.clear()
                    yield self._sse({"type": "aborted"})
                    break

                if self.queue:
                    event = self.queue.popleft()
                    yield self._sse(event)
                else:
                    await asyncio.sleep(0.05)
        except asyncio.CancelledError:
            logger.info("SSE stream cancelled for %s", self.id)
            raise

    @staticmethod
    def _sse(data: Dict[str, Any]) -> str:
        payload = json.dumps(data, ensure_ascii=False)
        return f"data: {payload}\n\n"


sessions: Dict[str, Session] = {}


def purge_expired_sessions() -> int:
    """Supprime les sessions inactives depuis plus de SESSION_TTL_SECONDS.

    Retourne le nombre de sessions purgées. Appelable depuis la boucle
    d'arrière-plan comme depuis les tests.
    """
    expired = [sid for sid, s in sessions.items() if s.expired and not s.busy]
    for sid in expired:
        del sessions[sid]
    if expired:
        logger.info("Purged %d expired session(s)", len(expired))
    return len(expired)


async def _purge_loop() -> None:
    """Boucle d'arrière-plan : purge toutes les 60s jusqu'à annulation."""
    while True:
        await asyncio.sleep(60)
        try:
            purge_expired_sessions()
        except Exception:
            logger.exception("Session purge failed")


# ── FastAPI app ───────────────────────────────────────────────────────
app = FastAPI(title="NaabigaCode Backend", version="0.2.0")


@app.on_event("startup")
async def _startup() -> None:
    app.state.purge_task = asyncio.create_task(_purge_loop())


@app.on_event("shutdown")
async def _shutdown() -> None:
    task = getattr(app.state, "purge_task", None)
    if task is not None:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


@app.get("/health")
async def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.post("/session/create")
async def create_session() -> Dict[str, str]:
    session_id = uuid.uuid4().hex[:12]
    sessions[session_id] = Session(session_id)
    logger.info("Created session %s", session_id)
    return {"session_id": session_id}


@app.post("/session/{session_id}/message")
async def send_message(session_id: str, payload: Dict[str, Any]) -> Dict[str, bool]:
    session = sessions.get(session_id)
    if not session:
        return {"accepted": False}

    if session.busy:
        session.emit({"type": "error", "message": "Session busy"})
        return {"accepted": False}

    user_message = str(payload.get("message", "")).strip()
    if not user_message:
        return {"accepted": False}

    session.busy = True
    session.emit({"type": "user", "text": user_message})

    asyncio.create_task(_run_turn(session, user_message))
    return {"accepted": True}


@app.post("/session/{session_id}/abort")
async def abort_session(session_id: str) -> Dict[str, bool]:
    session = sessions.get(session_id)
    if not session:
        return {"aborted": False}
    session.abort_event.set()
    return {"aborted": True}


@app.get("/session/{session_id}/events")
async def session_events(session_id: str) -> StreamingResponse:
    session = sessions.get(session_id)
    if not session:
        async def _empty():
            yield Session._sse({"type": "error", "message": "session not found"})

        return StreamingResponse(_empty(), media_type="text/event-stream")

    return StreamingResponse(
        session.stream_events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── Agent loop adapter ───────────────────────────────────────────────
async def _run_turn(session: Session, user_message: str) -> None:
    try:
        # 1. Commandes slash : interception AVANT tout appel LLM.
        #    handle_slash émet lui-même les événements et retourne :
        #      None       → prompt normal pour le moteur
        #      "consumed" → commande traitée, aucun tour LLM
        #      "rerun"    → commande `/retry` : rejouer le dernier prompt
        try:
            from tui_slash import handle_slash

            slash_action = handle_slash(session.id, session, user_message, session.emit)
        except Exception as exc:
            logger.warning("slash dispatch failed (%s) — fallback LLM", exc)
            slash_action = None

        if slash_action == "consumed":
            return
        if slash_action == "rerun":
            # /retry : rejoue le dernier message utilisateur (récupéré dans
            # la file d'événements) en tour LLM normal.
            for ev in reversed(list(session.queue)):
                if ev.get("type") == "user":
                    user_message = ev.get("text", "")
                    break

        # 2. Tour agent normal (LLM).
        from agent_bridge import run_turn_async

        result = await run_turn_async(
            session.id,
            user_message,
            emit=session.emit,
            provider=os.getenv("NAABIGA_INFERENCE_PROVIDER"),
            model=os.getenv("NAABIGA_INFERENCE_MODEL"),
        )
        final = result.get("final_response") or ""
        if result.get("failed") and not final:
            session.emit({"type": "error", "message": result.get("error") or "turn failed"})
        elif final and not result.get("streamed", False):
            # Sécurité : si aucun delta n'est parti, on renvoie la réponse finale.
            session.emit({"type": "assistant", "text": final})
    except Exception as exc:
        logger.exception("Agent turn failed: %s", exc)
        session.emit({"type": "error", "message": str(exc)})
    finally:
        session.emit({"type": "done"})
        session.busy = False


# ── Entrypoint ───────────────────────────────────────────────────────
def run_server(host: str = "127.0.0.1", port: int = 8400) -> None:
    logger.info("NaabigaCode backend listening on %s:%s", host, port)
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    run_server()
