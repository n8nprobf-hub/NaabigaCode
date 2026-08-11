import React, { useEffect, useRef, useState } from 'react'
import { Box, Text, useApp, useInput } from 'ink'
import Gradient from 'ink-gradient'
import Spinner from 'ink-spinner'
import TextInput from 'ink-text-input'
import { connectSession } from './sessionApi'
import type { SessionApi, SessionEvent } from './sessionApi'

// ── Palette Claude Code ────────────────────────────────────────────────
// Tool calls : nom coloré par famille + entrée/sortie en dim, comme le
// terminal Claude Code (Bash=bleu, Read=vert, Edit=jaune, Web=cyan…).
const TOOL_COLORS: Record<string, string> = {
  bash: 'blue',
  exec: 'blue',
  terminal: 'blue',
  run: 'blue',
  read_file: 'green',
  read: 'green',
  search_files: 'green',
  grep: 'green',
  edit: 'yellow',
  patch: 'yellow',
  write_file: 'yellow',
  write: 'yellow',
  browser: 'cyan',
  web: 'cyan',
  navigate: 'cyan',
}
function toolColor(name: string): string {
  const lower = name.toLowerCase()
  for (const [key, color] of Object.entries(TOOL_COLORS)) {
    if (lower.includes(key)) return color
  }
  return 'magenta'
}

// Tronque une valeur JSON pour l'afficher sur une ligne (comme le
// «+N lines» de Claude Code : on montre le début, on coupe le reste).
function truncate(value: unknown, max = 120): string {
  const raw = typeof value === 'string' ? value : JSON.stringify(value)
  if (!raw) return ''
  const oneLine = raw.replace(/\s+/g, ' ').trim()
  return oneLine.length > max ? `${oneLine.slice(0, max)}…` : oneLine
}

function EventLine({ event }: { event: SessionEvent }) {
  switch (event.type) {
    case 'user':
      // Message utilisateur en texte clair, comme Claude Code.
      return (
        <Box>
          <Text>{event.text}</Text>
        </Box>
      )
    case 'assistant':
      // Réponse assistant en blanc, streaming fusionné.
      return (
        <Box>
          <Text color="#e8b872">● </Text>
          <Text>{event.text}</Text>
        </Box>
      )
    case 'thinking':
      // «● Thinking…» en dim + détail, comme le mode think de Claude.
      return (
        <Box>
          <Text color="magenta" dimColor>
            <Spinner type="dots" /> thinking
          </Text>
          {event.text ? <Text color="gray"> — {event.text}</Text> : null}
        </Box>
      )
    case 'tool':
      // Carte compacte : nom coloré + entrée dim sur la même ligne,
      // sortie dim tronquée dessous — l'affichage «✳ Bash: cmd» de CC.
      return (
        <Box flexDirection="column">
          <Box>
            <Text color={toolColor(event.name)} bold>
              ✳ {event.name}
            </Text>
            {event.input !== undefined ? (
              <Text color="gray"> {truncate(event.input)}</Text>
            ) : null}
          </Box>
          {event.output !== undefined ? (
            <Text color="gray" dimColor>
              └ {truncate(event.output, 200)}
            </Text>
          ) : null}
        </Box>
      )
    case 'error':
      return <Text color="red">✕ {event.message}</Text>
    case 'info':
      return <Text color="blue" dimColor>{event.message}</Text>
    case 'done':
      return null
    case 'clear':
      return null
    case 'aborted':
      return <Text color="red" dimColor>✕ aborted</Text>
    default:
      return null
  }
}

interface Props {
  baseUrl: string
}

// Nombre max d'événements conservés à l'écran (anti-fuite mémoire sur
// les longues sessions).
const MAX_LINES = 200
// Nombre de tentatives + délai initial pour la création de session.
const CREATE_RETRIES = 3
const CREATE_RETRY_DELAY_MS = 1000

function pushLine(lines: SessionEvent[], ev: SessionEvent): SessionEvent[] {
  return [...lines.slice(-(MAX_LINES - 1)), ev]
}

// Fusionne les morceaux `assistant` consécutifs d'un même tour en un seul
// bloc (vrai rendu streaming : le texte s'accumule ligne par ligne au lieu
// d'empiler chaque chunk SSE comme entrée séparée). La fusion s'arrête
// d'elle-même : les tours sont séparés par des événements `user`/`tool`/
// `done` qui cassent la chaîne (le SSE pousse aussi `done` dans lines).
function appendEvent(lines: SessionEvent[], ev: SessionEvent): SessionEvent[] {
  if (ev.type !== 'assistant') return pushLine(lines, ev)
  const last = lines[lines.length - 1]
  if (last && last.type === 'assistant') {
    const merged: SessionEvent = { type: 'assistant', text: (last.text ?? '') + (ev.text ?? '') }
    return [...lines.slice(0, -1), merged]
  }
  return pushLine(lines, ev)
}

export default function App({ baseUrl }: Props) {
  const { exit } = useApp()
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [ready, setReady] = useState(false)
  const [busy, setBusy] = useState(false)
  const [lines, setLines] = useState<SessionEvent[]>([])
  // Champ de saisie contrôlé : valeur + curseur, vidé après chaque envoi
  // (UncontrolledTextInput garde le texte tapé après Enter — UX cassée).
  const [inputValue, setInputValue] = useState('')
  const apiRef = useRef<SessionApi | null>(null)

  // Create session on mount, with retries
  useEffect(() => {
    let cancelled = false
    void (async () => {
      for (let attempt = 1; attempt <= CREATE_RETRIES; attempt++) {
        const probe = connectSession(baseUrl, '__probe__')
        const sid = await probe.createSession()
        probe.close()
        if (cancelled) return
        if (sid) {
          setSessionId(sid)
          const api = connectSession(baseUrl, sid)
          apiRef.current = api
          // Rejoue l'historique de la session si le backend en a conservé
          // (nouvelle session → vide ; reconnexion → conversation complète).
          const history = await api.loadHistory()
          if (!cancelled) {
            if (history.length > 0) {
              // Fusionne aussi les morceaux assistant de l'historique rejoué
              // (même réduction que dans le handler SSE).
              setLines(history.reduce<SessionEvent[]>(appendEvent, []).slice(-MAX_LINES))
            }
            setReady(true)
          }
          return
        }
        if (attempt < CREATE_RETRIES) {
          await new Promise((r) => setTimeout(r, CREATE_RETRY_DELAY_MS * attempt))
        }
      }
      if (!cancelled) {
        setLines((prev) => pushLine(prev, { type: 'error', message: 'backend injoignable' }))
        setReady(true)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [baseUrl])

  // Stream events once session is up, with auto-reconnect
  useEffect(() => {
    const api = apiRef.current
    if (!api || !ready) return

    let stopped = false
    let timer: ReturnType<typeof setTimeout> | null = null

    const startStream = () => {
      if (stopped) return
      api.streamEvents(
        (ev) => {
          if (ev.type === 'clear') {
            // /clear : vide l'écran (événement consommé, non affiché).
            setLines([])
            return
          }
          // done/aborted sont poussés dans lines : invisibles à l'écran
          // (EventLine → null) mais ils scindent les tours successifs —
          // sans eux, le chunk assistant suivant fusionnerait avec le bloc
          // précédent. (Le backend ne les met pas dans /history, donc le
          // replay n'a pas ce problème.)
          setLines((prev) => appendEvent(prev, ev))
          if (ev.type === 'done' || ev.type === 'error' || ev.type === 'aborted') setBusy(false)
        },
        () => {
          setLines((prev) => pushLine(prev, { type: 'info', message: 'stream fermé, reconnexion…' }))
          setBusy(false)
          // Reconnexion automatique (backoff léger) tant que la session vit.
          if (!stopped) {
            timer = setTimeout(startStream, 1000)
          }
        },
      )
    }
    startStream()

    return () => {
      stopped = true
      if (timer) clearTimeout(timer)
      api.close()
    }
  }, [ready, apiRef])

  // Ctrl+C : abandonne la réponse en cours, puis quitte au second appui.
  useInput((_input, key) => {
    if (key.ctrl && _input === 'c') {
      if (busy) {
        void apiRef.current?.abort()
        setBusy(false)
      } else {
        exit()
      }
    }
  })

  const handleSubmit = async (value: string) => {
    const api = apiRef.current
    if (!api || busy) return
    setBusy(true)
    const ok = await api.sendMessage(value)
    setInputValue('') // vide le champ immédiatement (même si refusé : le texte est dans l'historique)
    if (!ok) {
      setLines((prev) => pushLine(prev, { type: 'error', message: 'message refusé (session occupée ?)' }))
      setBusy(false)
    }
  }

  return (
    <Box flexDirection="column">
      {/* Bandeau Claude Code : titre compact en dégradé orange + version */}
      <Box flexDirection="column" marginBottom={1}>
        <Box>
          <Gradient name="atlas">
            <Text bold>Naabiga Code</Text>
          </Gradient>
          <Text color="gray">  v0.2.0</Text>
        </Box>
        <Text color="gray">
          session {sessionId ?? '…'} · backend {baseUrl}
        </Text>
      </Box>

      {/* Conversation */}
      <Box flexDirection="column">
        {lines.map((ev, i) => (
          <EventLine key={i} event={ev} />
        ))}
      </Box>

      {/* Statut (mode Claude Code : ligne d'état discrète) */}
      <Box marginTop={1}>
        {busy ? (
          <Text color="green">
            <Spinner type="dots" /> working…
          </Text>
        ) : ready ? (
          <Text color="gray" dimColor>ready</Text>
        ) : (
          <Text color="yellow">
            <Spinner type="dots" /> connecting…
          </Text>
        )}
      </Box>

      {/* Prompt : ligne de séparation + ❯ comme Claude Code */}
      <Box marginTop={1} flexDirection="column">
        <Text color="gray" dimColor>─</Text>
        <Box>
          <Text color="white" bold>❯ </Text>
          <TextInput
            value={inputValue}
            onChange={setInputValue}
            onSubmit={handleSubmit}
            placeholder="Ask anything…"
          />
        </Box>
      </Box>
    </Box>
  )
}
