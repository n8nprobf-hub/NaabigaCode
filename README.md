# NaabigaCode

> **Le futur du développement logiciel s'écrit maintenant.**

Et si votre équipe pouvait déléguer la **génération**, la **correction** et le **refactoring** de code à un agent IA, directement depuis le terminal ?

**naabiga-cli** arrive : un agent de codage conçu par **ICONEDOR SARL** pour accompagner les entreprises et équipes tech d'Afrique de l'Ouest dans leur transformation digitale.

### ✅ Ce que naabiga-cli vous apporte

- **Génération de code autonome** — de la fonction isolée au module complet, l'agent écrit, corrige et itère jusqu'au résultat.
- **Compréhension du contexte de votre projet** — il lit votre codebase, vos conventions et vos contraintes avant d'agir.
- **Pensé pour les réalités et besoins des équipes locales** — connexions instables, ressources limitées, offline-first : l'outil s'adapte à votre environnement, pas l'inverse.
- **Un outil, une vision** — accélérer l'innovation depuis **Ouagadougou**, pour toute l'Afrique de l'Ouest.

---

## Pourquoi NaabigaCode ?

NaabigaCode est un **agent de codage souverain et local-first** :

- **Moteur agentique en Python** (hérité de Thot) — outils, MCP, gestion de contexte, multi-providers
- **Interface terminal en React/Ink** (style OpenClaude) — moderne, fluide, temps réel
- **100% local** — aucune télémétrie, aucun service cloud obligatoire, vos données restent chez vous
- **Multi-provider** — OpenAI-compatible, Gemini, Ollama, et bien d'autres, au choix de l'équipe

## Architecture

```
┌──────────────────────────────┐
│  frontend/ (React + Ink)     │   TUI terminal
│  src/cli.tsx → App.tsx       │   affiche la session, capture l'input
└──────────────┬───────────────┘
               │ HTTP + SSE (127.0.0.1:8400)
┌──────────────▼───────────────┐
│  backend/ (Python)           │   coeur agentique
│  main.py → FastAPI           │   /session/* endpoints
│  agent/ (ThotEngine)         │   conversation_loop, tools, context
│  thot_cli/                   │   CLI et utilitaires
└──────────────────────────────┘
```

## Démarrage rapide

### Installation (une commande)

**Linux / macOS :**

```bash
curl -fsSL https://naabigaCode.iconedor.com/install.sh | bash
```

**Windows (PowerShell) :**

```powershell
iex (irm https://naabigaCode.iconedor.com/install.ps1)
```

> Les URLs `naabigaCode.iconedor.com` pointent vers les mêmes scripts sur
> GitHub (`raw.githubusercontent.com/n8nprobf-hub/NaabigaCode/main/scripts/`).
> L'installateur détecte Node.js, tente `npm install -g naabiga-cli`, puis
> retombe sur le tarball officiel de la release GitHub. Il crée le venv
> Python et installe les dépendances automatiquement.

**Ou via npm (une fois publié sur le registry) :**

```bash
npm install -g naabiga-cli   # puis : naabiga
npx naabiga-cli              # sans installation
```

### Backend (Python)

```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
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

---

## Licence

NaabigaCode est distribué sous licence **MIT** — voir [LICENSE](LICENSE).

© **ICONEDOR SARL** — Ouagadougou, Burkina Faso. Construit pour les équipes tech d'Afrique de l'Ouest.
