#!/usr/bin/env node
/**
 * naabigacode — entrypoint CLI (package racine npm).
 *
 * Délègue à naabigacode-frontend (la TUI React/Ink buildée), qui résout
 * lui-même le backend Python (NAABIGA_BACKEND_MAIN → repo local →
 * ~/.naabiga/backend/main.py, installé par le postinstall).
 */
import { createRequire } from 'node:module'

const require = createRequire(import.meta.url)

// Résout le CLI buildé du frontend (dépendance du package racine).
let cliPath
try {
  cliPath = require.resolve('naabigacode-frontend/dist/cli.mjs')
} catch {
  console.error('[naabiga] frontend introuvable — réinstallez le package : npm install -g naabigacode')
  process.exit(1)
}

// import() direct avec le chemin absolu : Node gère les chemins Windows
// (C:\...) et POSIX (/...). PAS de new URL('file://' + path) — sur Windows
// ça casse avec ERR_UNSUPPORTED_ESM_URL_SCHEME (protocole 'c:').
await import(cliPath)
