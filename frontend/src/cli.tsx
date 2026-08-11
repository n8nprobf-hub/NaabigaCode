#!/usr/bin/env node
/**
 * NaabigaCode — entrypoint TUI console (Ink/React).
 *
 * Démarre le backend Python (FastAPI) en sous-processus si nécessaire,
 * puis affiche l'interface terminal connectée au flux SSE.
 *
 * Usage:
 *   naabiga                      # TUI interactive (backend auto-démarré)
 *   naabiga --backend-url http://127.0.0.1:8400   # backend déjà lancé
 */

import React from 'react'
import { render } from 'ink'
import { spawn, spawnSync } from 'node:child_process'
import { existsSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import App from './App'

const __dirname = dirname(fileURLToPath(import.meta.url))
const BACKEND_URL = process.env.NAABIGA_BACKEND_URL ?? 'http://127.0.0.1:8400'

function resolveBackendCommand(): { cmd: string; args: string[] } | null {
  // Chemins candidats pour backend/main.py, par priorité :
  // 1. NAABIGA_BACKEND_MAIN (variable d'env explicite — install npm)
  // 2. repo cloné local (dev) : on remonte depuis dist/ jusqu'à trouver
  //    backend/main.py (couvre frontend/dist → racine du repo)
  // 3. ~/.naabiga/backend/main.py (installation utilisateur)
  const explicit = process.env.NAABIGA_BACKEND_MAIN
  const candidates: string[] = []
  if (explicit) candidates.push(explicit)
  let dir = __dirname
  for (let i = 0; i < 6; i++) {
    const probe = join(dir, 'backend', 'main.py')
    if (existsSync(probe)) {
      candidates.push(probe)
      break
    }
    const parent = dirname(dir)
    if (parent === dir) break
    dir = parent
  }
  candidates.push(join(process.env.HOME || '', '.naabiga', 'backend', 'main.py'))

  const mainPy = candidates.find((p) => existsSync(p))
  if (!mainPy) return null

  // Chemins venv selon la plateforme : bin/ (Unix), Scripts/ (Windows).
  // mainPy = <root>/backend/main.py → root = parent du dossier backend.
  const root = dirname(dirname(mainPy))
  const venvCandidates = [
    join(root, 'backend', '.venv', 'bin', 'python'),
    join(root, 'backend', '.venv', 'Scripts', 'python.exe'),
    join(root, 'backend', 'venv', 'bin', 'python'),
    join(root, 'backend', 'venv', 'Scripts', 'python.exe'),
  ]
  for (const venvPy of venvCandidates) {
    if (existsSync(venvPy)) return { cmd: venvPy, args: [mainPy] }
  }
  // Fallback : python sur le PATH (noms selon la plateforme).
  const pathCandidates = ['python3', 'python', 'py']
  for (const py of pathCandidates) {
    if (py === 'py') {
      // `py` est un launcher Windows : il faut le flag -3 pour forcer Python 3.
      const probe = spawnSync(py, ['-3', '--version'], { stdio: 'ignore' })
      if (probe.status === 0) return { cmd: py, args: ['-3', mainPy] }
      continue
    }
    const probe = spawnSync(py, ['--version'], { stdio: 'ignore' })
    if (probe.status === 0) return { cmd: py, args: [mainPy] }
  }
  return null
}

function waitForBackend(url: string, timeoutMs = 20000): Promise<boolean> {
  const started = Date.now()
  return new Promise((resolvePromise) => {
    const tick = async () => {
      try {
        const res = await fetch(`${url}/health`)
        if (res.ok) return resolvePromise(true)
      } catch {
        // not up yet
      }
      if (Date.now() - started > timeoutMs) return resolvePromise(false)
      setTimeout(tick, 300)
    }
    void tick()
  })
}

async function main() {
  const args = process.argv.slice(2)
  const explicitUrlIdx = args.indexOf('--backend-url')
  const resumeIdx = args.indexOf('--resume')
  let baseUrl = BACKEND_URL
  let backendProc: ReturnType<typeof spawn> | null = null
  // --resume <session_id> : reprend une session existante au lieu d'en créer.
  const resumeSessionId = resumeIdx !== -1 && args[resumeIdx + 1] ? args[resumeIdx + 1] : undefined

  if (explicitUrlIdx !== -1 && args[explicitUrlIdx + 1]) {
    baseUrl = args[explicitUrlIdx + 1]
  } else {
    const backend = resolveBackendCommand()
    if (!backend) {
      console.error('[naabiga] backend Python introuvable — lancez "python3 backend/main.py" d\'abord')
      process.exit(1)
    }
    console.error(`[naabiga] démarrage du backend : ${backend.cmd} ${backend.args.join(' ')}`)
    backendProc = spawn(backend.cmd, backend.args, {
      stdio: ['ignore', 'pipe', 'pipe'],
      env: {
        ...process.env,
        // Config Naabiga : NAABIGA_HOME explicite si fourni, sinon home utilisateur.
        ...(process.env.NAABIGA_HOME ? {} : { NAABIGA_HOME: process.env.NAABIGA_HOME_NAABIGA ?? join(process.env.HOME || '', '.naabiga') }),
      },
    })
    backendProc.stdout?.on('data', (d) => process.stderr.write(`[backend] ${d}`))
    backendProc.stderr?.on('data', (d) => process.stderr.write(`[backend] ${d}`))
    backendProc.on('exit', (code) => {
      if (code && code !== 0) process.stderr.write(`[naabiga] backend arrêté (code ${code})\n`)
    })
  }

  const up = await waitForBackend(baseUrl)
  if (!up) {
    console.error(`[naabiga] backend injoignable sur ${baseUrl}`)
    backendProc?.kill()
    process.exit(1)
  }

  // exitOnCtrlC:false — le handler useInput d'App.tsx gère Ctrl+C (abort si
  // busy, exit au 2e appui). Sans cette option, Ink v6 quitte immédiatement
  // au 1er Ctrl+C et tue le backend en plein tour LLM.
  const { waitUntilExit } = render(<App baseUrl={baseUrl} initialSessionId={resumeSessionId} />, { exitOnCtrlC: false })
  try {
    await waitUntilExit()
  } finally {
    backendProc?.kill()
  }
}

main().catch((err) => {
  console.error(err)
  process.exit(1)
})
