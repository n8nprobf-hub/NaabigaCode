# naabigacode-frontend

Interface terminale (TUI) React/Ink du backend NaabigaCode. Remplace la
couche curses par un client moderne connecté au backend FastAPI via SSE.

## Prérequis

- **Node.js ≥ 20** et npm
- **Python 3** pour le backend (détecté automatiquement : venv du backend,
  puis `python3`/`python`/`py` sur le PATH)

## Installation

```bash
npm ci          # installe exactement les versions du package-lock
```

## Utilisation

```bash
# TUI interactive — démarre le backend en sous-processus si nécessaire
npm run dev

# Backend déjà lancé (ex. : python3 backend/main.py)
npm run dev -- --backend-url http://127.0.0.1:8400
```

Après build, le binaire est un exécutable autonome :

```bash
npm run build        # → dist/cli.mjs
npx .                # ou : node dist/cli.mjs
```

### Variables d'environnement

| Variable | Rôle |
|---|---|
| `NAABIGA_BACKEND_URL` | URL backend par défaut (`http://127.0.0.1:8400` si absent) |
| `NAABIGA_HOME` | Surcharge l'emplacement de configuration Naabiga |

### Commandes intégrées

- `Ctrl+C` : abandonne la réponse en cours puis quitte
- `/help` : liste les commandes slash du backend

## Contrat de session avec le backend

| Route | Rôle |
|---|---|
| `POST /session/create` | Nouvelle session `{ session_id }` |
| `POST /session/{id}/message` | Envoie un message `{ accepted }` |
| `GET /session/{id}/events` | Flux SSE d'événements (user/assistant/tool/…) |
| `GET /session/{id}/history` | Historique stable rejouable (reconnexion) |
| `POST /session/{id}/abort` | Abandonne la réponse en cours |
| `GET /health` | Healthcheck |

## Architecture

```
src/
├── cli.tsx         # Entrypoint : boot backend, healthcheck, rendu Ink
├── App.tsx         # UI : historique, input contrôlé, reconnexion SSE
└── sessionApi.ts   # Client HTTP + parseur SSE (fetch + ReadableStream)
scripts/build.mjs   # Bundle esbuild → dist/cli.mjs (packages externalisés)
```

Comportements notables :

- **Streaming** : les morceaux `assistant` consécutifs sont fusionnés en un
  seul bloc (pas une ligne par chunk SSE).
- **Reconnexion auto** : le stream SSE se reconnecte avec backoff léger tant
  que la session vit ; l'historique est rejoué via `/history` au démarrage.
- **Anti-fuite mémoire** : seules les 200 dernières lignes sont conservées.

## Scripts

| Script | Description |
|---|---|
| `npm run dev` | Lance la TUI en mode développement (`tsx`) |
| `npm run typecheck` | Vérification TypeScript strict (`tsc --noEmit`) |
| `npm run build` | Bundle esbuild → `dist/cli.mjs` |