#!/usr/bin/env node
/**
 * naabiga-cli — entrypoint de production.
 *
 * Lance la TUI Ink (frontend/dist/cli.mjs) qui démarre elle-même le backend
 * Python (backend/main.py) en sous-processus.
 *
 * Usage :
 *   naabiga                       # TUI interactive (backend auto-démarré)
 *   naabiga --backend-url URL     # backend distant déjà lancé
 *   naabiga --version
 */
import { existsSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = dirname(fileURLToPath(import.meta.url))
const ROOT = join(__dirname, '..')
const CLI_MJS = join(ROOT, 'frontend', 'dist', 'cli.mjs')
const VENV_PY = join(ROOT, 'backend', '.venv', 'bin', 'python')

// --version rapide (zéro chargement)
if (process.argv.slice(2).includes('--version') || process.argv.slice(2).includes('-v')) {
  console.log('naabiga-cli 0.2.0 (ICONEDOR SARL)')
  process.exit(0)
}

// Vérifications de production
if (!existsSync(VENV_PY)) {
  console.error('[naabiga] Environnement Python manquant. Relancez "npm install" ou "npm rebuild naabiga-cli" pour le créer.')
  process.exit(1)
}
if (!existsSync(CLI_MJS)) {
  console.error('[naabiga] TUI non buildée. Exécutez : npm run build --prefix frontend')
  process.exit(1)
}

await import(CLI_MJS)
