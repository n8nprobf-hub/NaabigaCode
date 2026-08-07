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
  const root = join(__dirname, '..', '..')
  const candidates = [
    { cmd: join(root, 'backend', '.venv', 'bin', 'python'), args: [join(root, 'backend', 'main.py')] },
    { cmd: 'python3', args: [join(root, 'backend', 'main.py')] },
  ]
  for (const c of candidates) {
    if (existsSync(c.cmd)) return c
    // python3 may be on PATH even if not on disk at that path
    if (c.cmd === 'python3') {
      const probe = spawnSync(c.cmd, ['--version'], { stdio: 'ignore' })
      if (probe.status === 0) return c
    }
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
  let baseUrl = BACKEND_URL
  let backendProc: ReturnType<typeof spawn> | null = null

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
        // Config Thot déjà existante sur la machine (sinon THOT_HOME par défaut).
        ...(process.env.THOT_HOME ? {} : { THOT_HOME: process.env.THOT_HOME_NAABIGA ?? '/opt/data/.thot-home' }),
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

  const { waitUntilExit } = render(<App baseUrl={baseUrl} />)
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
