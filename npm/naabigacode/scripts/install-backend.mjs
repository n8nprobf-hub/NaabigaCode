#!/usr/bin/env node
/**
 * Postinstall naabigacode — installe le backend Python dans ~/.naabiga/backend.
 *
 * Le package npm embarque la TUI (frontend buildé) mais PAS le backend
 * (38 Mo, 580K lignes — trop lourd pour un tarball npm). Ce script :
 *   1. télécharge le tarball du backend depuis GitHub (branche main)
 *   2. l'extrait dans ~/.naabiga/backend (skippé si déjà présent)
 *   3. crée un venv Python + installe requirements.txt
 *
 * Le frontend (naabiga) résout ensuite NAABIGA_BACKEND_MAIN lui-même.
 */
import { execSync } from 'node:child_process'
import { existsSync, mkdirSync, rmSync } from 'node:fs'
import { join } from 'node:path'
import { homedir } from 'node:os'
import { tmpdir } from 'node:os'

const HOME = process.env.NAABIGA_HOME || join(homedir(), '.naabiga')
const BACKEND_DIR = join(HOME, 'backend')
const MAIN_PY = join(BACKEND_DIR, 'main.py')
// Pinned à un commit stable (pas de tag de release : on suit main).
const SOURCE_URL = 'https://github.com/n8nprobf-hub/NaabigaCode/archive/refs/heads/main.tar.gz'

function log(msg) {
  console.log(`[naabiga] ${msg}`)
}

function run(cmd, opts = {}) {
  execSync(cmd, { stdio: 'inherit', ...opts })
}

async function main() {
  if (existsSync(MAIN_PY)) {
    log(`backend déjà installé : ${MAIN_PY}`)
    return
  }

  mkdirSync(HOME, { recursive: true })
  log(`installation du backend Python dans ${BACKEND_DIR}…`)

  // 1. Téléchargement du tarball GitHub (repo public, branche main).
  const tarball = join(tmpdir(), `naabigacode-backend-${Date.now()}.tar.gz`)
  const extractDir = join(tmpdir(), `naabigacode-src-${Date.now()}`)
  try {
    log('téléchargement (peut prendre quelques minutes)…')
    run(`curl -fsSL "${SOURCE_URL}" -o "${tarball}"`)
    mkdirSync(extractDir, { recursive: true })
    run(`tar -xzf "${tarball}" -C "${extractDir}"`)

    // 2. Copie du dossier backend/ (le tarball contient NaabigaCode-main/backend).
    const srcRoot = join(extractDir, 'NaabigaCode-main')
    const srcBackend = join(srcRoot, 'backend')
    if (!existsSync(srcBackend)) {
      throw new Error(`backend introuvable dans le tarball (${srcBackend})`)
    }
    run(`mkdir -p "${BACKEND_DIR}"`)
    // cp -a pour conserver les permissions/liens.
    run(`cp -a "${srcBackend}/." "${BACKEND_DIR}/"`)

    // 3. Venv Python + requirements.
    const venvPy = process.platform === 'win32' ? join(BACKEND_DIR, '.venv', 'Scripts', 'python.exe') : join(BACKEND_DIR, '.venv', 'bin', 'python')
    if (!existsSync(venvPy)) {
      log('création du venv Python…')
      run(`python3 -m venv "${join(BACKEND_DIR, '.venv')}"`)
    }
    log('installation des dépendances (pip install -r requirements.txt)…')
    run(`"${venvPy}" -m pip install --quiet --upgrade pip`)
    run(`"${venvPy}" -m pip install --quiet -r "${join(BACKEND_DIR, 'requirements.txt')}"`)

    log('✅ backend prêt : ' + MAIN_PY)
  } finally {
    rmSync(tarball, { force: true })
    rmSync(extractDir, { recursive: true, force: true })
  }
}

main().catch((err) => {
  console.error(`[naabiga] échec de l'installation du backend : ${err.message}`)
  console.error('[naabiga] relancez : npm rebuild naabigacode  (ou supprimez ~/.naabiga/backend et réinstallez)')
  process.exit(1)
})
