# NaabigaCode

**Moteur agentique Python (hérité de Thot) + TUI terminal React/Ink (style OpenClaude).**

NaabigaCode conserve tout le coeur fonctionnel de Thot en Python, et le branche
sur une interface terminal écrite en React (Ink), comme OpenClaude.

## Architecture

```
┌──────────────────────────────┐
│  frontend/ (React + Ink)     │   TUI terminal
│  src/cli.tsx → App.tsx       │   affiche la session, capture l'input
└──────────────┬───────────────┘
               │ HTTP + SSE (127.0.0.1:8400)
┌──────────────▼───────────────┐
│  backend/ (Python)           │   coeur agentique Thot
│  main.py → FastAPI           │   /session/* endpoints
│  agent/ (ThotEngine)         │   conversation_loop, tools, context
│  thot_cli/                   │   CLI et utilitaires Thot
└──────────────────────────────┘
```

## Démarrage rapide

### Backend (Python)

```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install fastapi 'uvicorn[standard]'
.venv/bin/python main.py
# → http://127.0.0.1:8400 (health: /health)
```

### Frontend (React/Ink)

```bash
cd frontend
npm install
npm run build     # → dist/cli.mjs
node dist/cli.mjs # TUI interactive (démarre le backend automatiquement)
```

En dev :

```bash
cd frontend
npm run dev       # tsx src/cli.tsx
```

### API du backend

| Méthode | Endpoint | Description |
|---|---|---|
| `POST` | `/session/create` | Crée une session → `{session_id}` |
| `POST` | `/session/{id}/message` | Envoie un message → `{accepted}` |
| `GET` | `/session/{id}/events` | Flux SSE des événements |
| `POST` | `/session/{id}/abort` | Interrompt le tour en cours |
| `GET` | `/health` | Healthcheck |

### Événements SSE

```json
{"type":"user","text":"..."}
{"type":"assistant","text":"..."}
{"type":"thinking","text":"..."}
{"type":"tool","name":"...","input":{},"output":{}}
{"type":"error","message":"..."}
{"type":"done"}
{"type":"aborted"}
```

## Contrat UI ↔ moteur

Le frontend **ne touche jamais** au moteur directement. Il passe par le bridge
HTTP/SSE :

1. `cli.tsx` démarre `backend/main.py` en sous-processus (ou utilise un backend distant via `--backend-url`).
2. `App.tsx` crée une session, ouvre le flux SSE, affiche les événements.
3. À chaque saisie, `POST /session/{id}/message` → le moteur tourne → événements streamés vers la TUI.
4. `Ctrl+C` envoie `POST /session/{id}/abort` puis quitte.

## Notes

- La partie agent reste 100% Python (`backend/agent/`, `backend/thot_cli/`).
- La TUI est 100% React/Ink (`frontend/`), modèle OpenClaude.
- Le backend est local-first : aucune télémétrie, aucun service cloud requis.
