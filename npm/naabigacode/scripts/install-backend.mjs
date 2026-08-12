#!/usr/bin/env node
/**
 * Postinstall naabigacode — installe le backend Python dans ~/.naabiga/backend.
 *
 * Le package npm embarque la TUI (frontend buildé) mais PAS le backend
 * (38 Mo, 580K lignes — trop lourd pour un tarball npm). Ce script :
 *   1. télécharge le tarball du backend depuis GitHub (tag de release)
 *   2. l'extrait dans ~/.naabiga/backend (skippé si déjà présent)
 *   3. crée un venv Python + installe requirements.txt
 *
 * Cross-platform (Windows + POSIX) : curl/tar sont fournis par Windows 10+,
 * les opérations fichiers passent par les API Node (cpSync/mkdirSync), et
 * la détection Python essaie python3 / python / py -3 (le shim WindowsApps
 * « python3 » peut ouvrir le Store au lieu d'exécuter un vrai Python).
 *
 * Le frontend (naabiga) résout ensuite NAABIGA_BACKEND_MAIN lui-même.
 */
import { execSync, spawnSync } from 'node:child_process'
import { existsSync, mkdirSync, cpSync, readdirSync, rmSync } from 'node:fs'
import { join } from 'node:path'
import { homedir, tmpdir } from 'node:os'

const HOME = process.env.NAABIGA_HOME || join(homedir(), '.naabiga')
const BACKEND_DIR = join(HOME, 'backend')
const MAIN_PY = join(BACKEND_DIR, 'main.py')
// Source pinnée à un TAG de release (pas la branche main mouvante) :
// reproductibilité + intégrité (le tarball GitHub d'un tag est immuable).
const SOURCE_TAG = 'v0.3.0'
const SOURCE_URL = `https://github.com/n8nprobf-hub/NaabigaCode/archive/refs/tags/${SOURCE_TAG}.tar.gz`

const IS_WIN = process.platform === 'win32'

function log(msg) {
  console.log(`[naabiga] ${msg}`)
}

function run(cmd, opts = {}) {
  execSync(cmd, { stdio: 'inherit', ...opts })
}

/** Détecte un interpréteur Python utilisable : python3, python, py -3. */
function findPython() {
  const candidates = [
    { cmd: 'python3', args: [] },
    { cmd: 'python', args: [] },
    { cmd: 'py', args: ['-3'] },
  ]
  for (const { cmd, args } of candidates) {
    const probe = spawnSync(cmd, [...args, '--version'], { stdio: 'ignore' })
    if (probe.error || probe.status !== 0) continue
    return { cmd, args }
  }
  return null
}

async function main() {
  if (existsSync(MAIN_PY)) {
    log(`backend déjà installé : ${MAIN_PY}`)
    return
  }

  mkdirSync(HOME, { recursive: true })
  log(`installation du backend Python dans ${BACKEND_DIR}…`)

  // 1. Téléchargement du tarball GitHub (repo public, tag de release).
  const tarball = join(tmpdir(), `naabigacode-backend-${Date.now()}.tar.gz`)
  const extractDir = join(tmpdir(), `naabigacode-src-${Date.now()}`)
  try {
    log('téléchargement (peut prendre quelques minutes)…')
    run(`curl -fsSL "${SOURCE_URL}" -o "${tarball}"`)
    mkdirSync(extractDir, { recursive: true })
    run(`tar -xzf "${tarball}" -C "${extractDir}"`)

    // 2. Copie du dossier backend/ — le tarball extrait s'appelle
    //    NaabigaCode-<tag> (ex: NaabigaCode-v0.3.0 → NaabigaCode-0.3.0 sans le
    //    « v »). On cherche le dossier contenant backend/main.py de façon
    //    robuste (peu importe le préfixe).
    const srcRoot = [...readdirSync(extractDir)].map((n) => join(extractDir, n)).find((p) => existsSync(join(p, 'backend', 'main.py')))
    if (!srcRoot) {
      throw new Error(`backend/main.py introuvable dans le tarball (extrait dans ${extractDir})`)
    }
    const srcBackend = join(srcRoot, 'backend')
    mkdirSync(BACKEND_DIR, { recursive: true })
    cpSync(srcBackend, BACKEND_DIR, { recursive: true })

    // 3. Venv Python + requirements.
    const venvPy = IS_WIN
      ? join(BACKEND_DIR, '.venv', 'Scripts', 'python.exe')
      : join(BACKEND_DIR, '.venv', 'bin', 'python')
    if (!existsSync(venvPy)) {
      const py = findPython()
      if (!py) {
        throw new Error(
          'Python 3 introuvable sur PATH (essayé python3, python, py -3). ' +
            'Installez Python >= 3.10 depuis https://python.org puis relancez : npm rebuild naabigacode',
        )
      }
      log(`création du venv Python (${py.cmd})…`)
      run(`"${py.cmd}" ${py.args.join(' ')} -m venv "${join(BACKEND_DIR, '.venv')}"`.trim())
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
