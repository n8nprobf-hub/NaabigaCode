import React, { useEffect, useRef, useState } from 'react'
import { Box, Text, useApp, useInput } from 'ink'
import Gradient from 'ink-gradient'
import BigText from 'ink-big-text'
import Spinner from 'ink-spinner'
import TextInput from 'ink-text-input'
import { connectSession } from './sessionApi'
import type { SessionApi, SessionEvent } from './sessionApi'

function EventLine({ event }: { event: SessionEvent }) {
  switch (event.type) {
    case 'user':
      return (
        <Box>
          <Text color="cyan">❯ </Text>
          <Text>{event.text}</Text>
        </Box>
      )
    case 'assistant':
      return <Text>{event.text}</Text>
    case 'thinking':
      return (
        <Box>
          <Text color="yellow">
            <Spinner type="dots" /> thinking
          </Text>
          {event.text ? <Text color="gray"> — {event.text}</Text> : null}
        </Box>
      )
    case 'tool':
      return (
        <Box flexDirection="column">
          <Text color="magenta">[tool] {event.name}</Text>
          {event.input !== undefined ? (
            <Text color="gray">in: {JSON.stringify(event.input)}</Text>
          ) : null}
          {event.output !== undefined ? (
            <Text color="gray">out: {JSON.stringify(event.output)}</Text>
          ) : null}
        </Box>
      )
    case 'error':
      return <Text color="red">error: {event.message}</Text>
    case 'info':
      return <Text color="blue">info: {event.message}</Text>
    case 'done':
      return null
    case 'clear':
      return null
    case 'aborted':
      return <Text color="red">[aborted]</Text>
    default:
      return null
  }
}

interface Props {
  baseUrl: string
}

// Nombre max d'événements conservés à l'écran (anti fuite mémoire sur
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
        const probe = connectSession(baseUrl, 'probe')
        const sid = await probe.createSession()
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
          setLines((prev) => pushLine(prev, { type: 'info', message: `backend pas prêt (tentative ${attempt}/${CREATE_RETRIES})…` }))
          await new Promise((r) => setTimeout(r, CREATE_RETRY_DELAY_MS))
        }
      }
      setLines((prev) => pushLine(prev, { type: 'error', message: `Backend injoignable sur ${baseUrl} après ${CREATE_RETRIES} tentatives` }))
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
  }, [ready])

  useInput((input, key) => {
    if (key.ctrl && input.toLowerCase() === 'c') {
      void apiRef.current?.abort()
      exit()
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
    <Box flexDirection="column" minHeight="100%">
      {!ready ? (
        <Box justifyContent="center">
          <Spinner type="dots" />
          <Text color="gray"> initialisation de la session…</Text>
        </Box>
      ) : (
        <Box flexDirection="column" flexGrow={1}>
          <Box justifyContent="center" paddingY={1}>
            <Gradient name="fruit">
              <BigText text="NAABIGACODE" font="tiny" />
            </Gradient>
          </Box>
          <Box paddingX={1}>
            <Text color="gray" dimColor>
              session {sessionId} — Ctrl+C pour quitter
            </Text>
          </Box>
          <Box flexGrow={1} flexDirection="column" paddingX={1}>
            {lines.map((ev, i) => (
              <EventLine key={i} event={ev} />
            ))}
            {busy ? (
              <Box>
                <Text color="yellow">
                  <Spinner type="dots" /> reasoning
                </Text>
              </Box>
            ) : null}
          </Box>
          <Box>
            <Text color="green">❯ </Text>
            <TextInput
              value={inputValue}
              onChange={setInputValue}
              onSubmit={handleSubmit}
              placeholder="Ask anything…"
            />
          </Box>
        </Box>
      )}
    </Box>
  )
}
