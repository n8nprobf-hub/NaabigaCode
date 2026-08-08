#!/usr/bin/env node
/**
 * naabiga-cli — postinstall
 *
 * Prépare l'environnement de production :
 *   1. Vérifie que Python 3 est disponible
 *   2. Crée le venv backend/.venv s'il n'existe pas
 *   3. Installe les dépendances Python (requirements.txt)
 *   4. Vérifie que la TUI est buildée (frontend/dist/cli.mjs)
 */
import { existsSync } from 'node:fs'
import { spawnSync } from 'node:child_process'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = dirname(fileURLToPath(import.meta.url))
const ROOT = join(__dirname, '..')
const BACKEND = join(ROOT, 'backend')
const VENV = join(BACKEND, '.venv')
const VENV_PY = join(VENV, 'bin', 'python')
const CLI_MJS = join(ROOT, 'frontend', 'dist', 'cli.mjs')

function log(msg) {
  console.log(`[naabiga] ${msg}`)
}

function fail(msg) {
  console.error(`[naabiga] ${msg}`)
  process.exit(1)
}

function run(cmd, args, cwd) {
  const res = spawnSync(cmd, args, { cwd, stdio: 'inherit', env: process.env })
  if (res.error) fail(`${cmd} : ${res.error.message}`)
  return res.status ?? 1
}

// 1. Python 3 disponible ?
const pyProbe = spawnSync('python3', ['--version'], { stdio: 'ignore' })
if (pyProbe.error || pyProbe.status !== 0) {
  fail('Python 3 est requis mais introuvable sur PATH. Installez Python >= 3.10 puis relancez "npm install".')
}
log(`Python détecté : ${spawnSync('python3', ['--version']).stdout?.toString().trim() || '3.x'}`)

// 2. Venv
if (!existsSync(VENV_PY)) {
  log('Création de l\'environnement Python (venv)…')
  const status = run('python3', ['-m', 'venv', VENV], BACKEND)
  if (status !== 0) fail('Échec de création du venv Python.')
} else {
  log('venv Python déjà présent.')
}

// 3. Dépendances Python
log('Installation des dépendances Python (requirements.txt)…')
const pipStatus = run(VENV_PY, ['-m', 'pip', 'install', '--quiet', '-r', join(BACKEND, 'requirements.txt')], BACKEND)
if (pipStatus !== 0) fail('Échec de l\'installation des dépendances Python. Réessayez avec "npm rebuild naabiga-cli".')

// 4. TUI buildée ?
if (!existsSync(CLI_MJS)) {
  log('La TUI n\'est pas buildée — exécutez "npm run build --prefix frontend" (ou "npx naabiga --help" après publication).')
} else {
  log('TUI prête.')
}

log('Installation terminée. Lancez "naabiga" pour démarrer.')
