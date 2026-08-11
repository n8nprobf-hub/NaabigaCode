# NaabigaCode

**Agentic coding en terminal** — TUI React/Ink style Claude Code + backend Python (FastAPI).

## Installation

```bash
npm install -g naabigacode
```

L'installation télécharge automatiquement le backend Python dans `~/.naabiga/backend`
(venv + dépendances) — aucune autre commande nécessaire.

## Utilisation

```bash
naabiga                          # TUI interactive (backend auto-démarré)
naabiga --backend-url http://127.0.0.1:8400   # backend déjà lancé ailleurs
naabiga --resume <session_id>    # reprend une session existante
```

## Commandes slash dans la TUI

`/help` · `/status` · `/clear` · `/history` · `/retry` · `/title <nom>` ·
`/session` · `/sessions` · `/new` · `/whoami` · `/skills` · `/memory`

## Variables d'environnement

| Variable | Rôle |
|---|---|
| `NAABIGA_BACKEND_URL` | URL du backend (défaut `http://127.0.0.1:8400`) |
| `NAABIGA_BACKEND_MAIN` | Chemin explicite vers `backend/main.py` (outrepasse l'auto-détection) |
| `NAABIGA_HOME` | Dossier d'installation du backend (défaut `~/.naabiga`) |

## Architecture

```
naabigacode (npm, racine)          ← postinstall : backend Python dans ~/.naabiga
└── naabigacode-frontend (npm)     ← TUI buildée (React/Ink, esbuild)
    └── backend/ (Python FastAPI)  ← téléchargé depuis GitHub, venv dédié
        ├── main.py                ← API HTTP/SSE (sessions, événements)
        └── run_agent.py           ← boucle agent (LLM, outils, mixins)
```

## Développement

```bash
git clone https://github.com/n8nprobf-hub/NaabigaCode.git
cd NaabigaCode/frontend && npm ci && npm run dev
```

## Licence

MIT — ICONEDOR SARL (Naabiga)
