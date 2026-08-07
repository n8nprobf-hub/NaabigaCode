import React, { useEffect, useRef, useState } from 'react'
import { Box, Text, useApp, useInput } from 'ink'
import Gradient from 'ink-gradient'
import BigText from 'ink-big-text'
import Spinner from 'ink-spinner'
import { UncontrolledTextInput } from 'ink-text-input'
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
    case 'aborted':
      return <Text color="red">[aborted]</Text>
    default:
      return null
  }
}

interface Props {
  baseUrl: string
}

export default function App({ baseUrl }: Props) {
  const { exit } = useApp()
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [ready, setReady] = useState(false)
  const [busy, setBusy] = useState(false)
  const [lines, setLines] = useState<SessionEvent[]>([])
  const apiRef = useRef<SessionApi | null>(null)

  // Create session on mount
  useEffect(() => {
    let cancelled = false
    void (async () => {
      const probe = connectSession(baseUrl, 'probe')
      const sid = await probe.createSession()
      if (cancelled) return
      if (sid) {
        setSessionId(sid)
        setReady(true)
        apiRef.current = connectSession(baseUrl, sid)
      } else {
        setLines((prev) => [...prev, { type: 'error', message: `Backend injoignable sur ${baseUrl}` }])
      }
    })()
    return () => {
      cancelled = true
    }
  }, [baseUrl])

  // Stream events once session is up
  useEffect(() => {
    const api = apiRef.current
    if (!api || !ready) return
    api.streamEvents(
      (ev) => {
        setLines((prev) => [...prev, ev])
        if (ev.type === 'done' || ev.type === 'error' || ev.type === 'aborted') setBusy(false)
      },
      () => {
        setLines((prev) => [...prev, { type: 'info', message: 'stream fermé' }])
        setBusy(false)
      },
    )
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
    if (!ok) {
      setLines((prev) => [...prev, { type: 'error', message: 'message refusé (session occupée ?)' }])
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
            <UncontrolledTextInput
              placeholder="Ask anything…"
              onSubmit={handleSubmit}
            />
          </Box>
        </Box>
      )}
    </Box>
  )
}
