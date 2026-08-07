import React, { useEffect, useRef, useState } from 'react'
import { Box, Text, useApp, useInput, useStdin } from 'ink'
import Gradient from 'ink-gradient'
import BigText from 'ink-big-text'
import Spinner from 'ink-spinner'
import TextInput from 'ink-text-input'
import { useSessionEvents } from './useSessionEvents'
import type { SessionEvent } from './useSessionEvents'

function PromptRow({ onSubmit }: { onSubmit: (value: string) => void }) {
  const { isRawModeSupported } = useStdin()
  const [value, setValue] = useState('')

  if (!isRawModeSupported) {
    return <Text color="gray">Prompt indisponible (stdin non RAW).</Text>
  }

  return (
    <Box>
      <Text color="green">❯</Text>
      <Text color="gray"> </Text>
      <TextInput
        value={value}
        onChange={setValue}
        onSubmit={onSubmit}
        placeholder="Ask anything…"
      />
    </Box>
  )
}

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
    case 'aborted':
      return <Text color="red">[aborted]</Text>
    default:
      return null
  }
}

export default function App() {
  const { exit } = useApp()
  const { connect, sendMessage, createSession, abort } = useSessionEvents(null)
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [ready, setReady] = useState(false)
  const [input, setInput] = useState('')
  const [lines, setLines] = useState<SessionEvent[]>([])
  const [busy, setBusy] = useState(false)
  const esRef = useRef<EventSource | null>(null)

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      const sid = await createSession()
      if (!cancelled && sid) {
        setSessionId(sid)
        setReady(true)
      }
    })()
    return () => {
      cancelled = true
      esRef.current?.close()
    }
  }, [createSession])

  useEffect(() => {
    if (!sessionId || !connect) return
    const es = connect()
    esRef.current = es

    es.addEventListener('error', () => setReady(false))

    const handler = (ev: MessageEvent) => {
      try {
        const data = JSON.parse(ev.data) as SessionEvent
        setLines((prev) => [...prev, data])
        if (data.type === 'done' || data.type === 'error') setBusy(false)
      } catch {
        // ignore non-JSON keep-alives
      }
    }
    es.addEventListener('message', handler)
    return () => {
      es.removeEventListener('message', handler)
      es.close()
    }
  }, [sessionId, connect])

  useInput(async (_input, key) => {
    if (key.ctrl && key.c) {
      if (sessionId && abort) await abort(sessionId)
      exit()
    }
  })

  const handleSubmit = async (value: string) => {
    if (!sessionId || !sendMessage || busy) return
    setBusy(true)
    const ok = await sendMessage(sessionId, value)
    if (ok) {
      setLines((prev) => [...prev, { type: 'user', text: value }])
    } else {
      setBusy(false)
    }
  }

  return (
    <Box flexDirection="column" height="100%">
      {!ready ? (
        <Box justifyContent="center" flexGrow={1}>
          <Spinner type="dots" />
          <Text color="gray"> initialisation de la session…</Text>
        </Box>
      ) : (
        <Box flexDirection="column" flexGrow={1}>
          <Box justifyContent="center" paddingY={1}>
            <Gradient name="fruit">
              <BigText text="NAABIGACODE" font='tiny' />
            </Gradient>
            <Box paddingTop={1}>
              <Text color="gray" dimColor>
                session {sessionId} — tape Ctrl+C pour quitter
              </Text>
            </Box>
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
            <PromptRow onSubmit={handleSubmit} />
          </Box>
        </Box>
      )}
    </Box>
  )
}
