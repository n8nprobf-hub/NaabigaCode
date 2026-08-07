/**
 * NaabigaCode frontend build — bundle la TUI Ink (React) en un seul
 * exécutable Node ESM avec esbuild.
 */
import { build } from 'esbuild'
import { mkdirSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = dirname(fileURLToPath(import.meta.url))
const root = join(__dirname, '..')
const outdir = join(root, 'dist')

mkdirSync(outdir, { recursive: true })

await build({
  entryPoints: [join(root, 'src', 'cli.tsx')],
  outfile: join(outdir, 'cli.mjs'),
  bundle: true,
  platform: 'node',
  format: 'esm',
  target: 'node20',
  // Externalise tous les packages npm ; ne bundle que le code local.
  packages: 'external',
  logLevel: 'info',
})

console.log('[naabiga] frontend build OK → dist/cli.mjs')
