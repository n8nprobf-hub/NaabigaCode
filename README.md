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

- **Moteur agentique en Python** (hérité du projet Thot, rebaptisé Naabiga) — outils, MCP, gestion de contexte, multi-providers
- **Interface terminal en React/Ink** — moderne, fluide, temps réel
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
│  agent/ (NaabigaEngine)     │   conversation_loop, tools, context
│  naabiga_cli/               │   CLI et utilitaires
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

> **Statut npm :** le package n'est pas encore publié sur le registry npm.
> L'installation officielle passe par le tarball GitHub (release `v0.2.0`),
> géré automatiquement par l'installateur ci-dessus. La commande npm
> ci-dessous ne fonctionnera que lorsque la publication sera faite.

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

## Guide d'utilisation

### 1. Lancer une session

```bash
naabiga                    # session interactive dans le terminal
naabiga --backend-url http://127.0.0.1:8400   # backend déjà lancé ailleurs
naabiga --version          # vérifier l'installation
```

Une fois la TUI affichée, tapez directement votre demande puis `Entrée`.
`Ctrl+C` interrompt le tour en cours puis quitte la session.

### 2. Générer du code

L'agent comprend le contexte de votre projet (fichiers, conventions, outils) :
il lit, écrit et exécute directement dans votre dépôt.

```text
Crée un module Python de validation d'email (format, domaines jetables,
DNS MX) avec tests unitaires, dans src/validation/
```

```text
Ajoute une route /api/health qui renvoie {status: "ok"} avec le temps de
réponse, en suivant le style des routes existantes du projet
```

### 3. Corriger un bug

```text
Le script scripts/deploy.py échoue avec "KeyError: 'REGION'" quand
REGION n'est pas définie. Corrige-le et ajoute un message d'erreur clair.
```

```text
Les tests de auth.test.ts passent en local mais échouent en CI.
Analyse la différence d'environnement et corrige.
```

### 4. Refactorer / nettoyer

```text
Refactorise le fichier services/order.py : extrais la logique de calcul
de taxe dans un module dédié, garde la même API publique, et mets à jour
les tests existants.
```

```text
Identifie le code mort dans src/utils/ et propose une liste de fichiers
supprimables avec la justification de chaque suppression.
```

### 5. Comprendre une base de code

```text
Explique-moi l'architecture de ce projet : points d'entrée, flux de
données principal, et où sont les couches métier vs infrastructure.
```

```text
Où et comment les permissions sont-elles vérifiées dans ce dépôt ?
Montre-moi le chemin de code exact.
```

### 6. Exécuter des commandes

L'agent peut lancer des commandes dans votre terminal (tests, builds,
git) et en analyser les résultats :

```text
Lance les tests du module auth, analyse les échecs et corrige-les un par
un jusqu'à ce que tout passe.
```

```text
Crée une branche feature/payment-fix, applique la correction que tu as
proposée, et committe avec un message clair.
```

### 7. Multi-tours et historique

- **Poursuivre** : l'agent garde le contexte de la session — vous pouvez
  enchaîner « et maintenant », « autrement », « essaie encore ».
- **Changer de direction** : décrivez simplement le nouveau besoin, il
  adapte son plan.
- **Arrêter** : `Ctrl+C` interrompt proprement le tour en cours.

### 8. Trucs et astuces

| Astuce | Exemple |
|---|---|
| **Soyez précis sur le chemin** | « dans `src/services/` » plutôt que « quelque part » |
| **Donnez le comportement attendu** | « qui renvoie 404 si l'id n'existe pas » |
| **Citez les erreurs exactes** | collez le message d'erreur complet |
| **Demandez des tests adjacents** | « avec tests » / « mets à jour les tests » |
| **Exigez la vérification** | « lance les tests pour prouver que ça marche » |
| **Itérez** | « presque — le cas limite X casse encore » |

### 9. Résolution de problèmes

| Problème | Solution |
|---|---|
| `naabiga` introuvable | `export PATH="$HOME/.naabiga/node_modules/.bin:$PATH"` (ou nouveau terminal) |
| Backend injoignable | Vérifiez `curl http://127.0.0.1:8400/health` ; relancez `naabiga` |
| Aucun provider configuré | Configurez `NAABIGA_HOME/config.yaml` (provider + modèle + clé API) |
| Tools désactivés | Vérifiez `platform_toolsets.cli` dans la config (ex. `naabiga-cli`) |
| Python introuvable | Installez Python ≥ 3.10 puis relancez l'installateur |

## Contrat UI ↔ moteur

Le frontend **ne touche jamais** au moteur directement. Il passe par le bridge
HTTP/SSE :

1. `cli.tsx` démarre `backend/main.py` en sous-processus (ou utilise un backend distant via `--backend-url`).
2. `App.tsx` crée une session, ouvre le flux SSE, affiche les événements.
3. À chaque saisie, `POST /session/{id}/message` → le moteur tourne → événements streamés vers la TUI.
4. `Ctrl+C` envoie `POST /session/{id}/abort` puis quitte.

## Notes

- La partie agent reste 100% Python (`backend/agent/`, `backend/naabiga_cli/`).
- La TUI est 100% React/Ink (`frontend/`).
- Le backend est local-first : aucune télémétrie, aucun service cloud requis.

---

## Licence

NaabigaCode est distribué sous licence **MIT** — voir [LICENSE](LICENSE).

© **ICONEDOR SARL** — Ouagadougou, Burkina Faso. Construit pour les équipes tech d'Afrique de l'Ouest.
