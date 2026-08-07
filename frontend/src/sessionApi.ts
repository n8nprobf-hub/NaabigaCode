/**
 * Client SSE + HTTP pour le backend NaabigaCode.
 * Fonctionne dans Node (fetch + ReadableStream) et navigateur (EventSource fallback).
 */

export type SessionEvent =
  | { type: 'user'; text: string }
  | { type: 'assistant'; text: string }
  | { type: 'tool'; name: string; input?: unknown; output?: unknown }
  | { type: 'thinking'; text?: string }
  | { type: 'error'; message: string }
  | { type: 'done' }
  | { type: 'aborted' }
  | { type: 'info'; message: string }

export interface SessionApi {
  createSession(): Promise<string | null>
  sendMessage(message: string): Promise<boolean>
  abort(): Promise<void>
  streamEvents(onEvent: (ev: SessionEvent) => void, onClose: () => void): void
  close(): void
}

export function connectSession(baseUrl: string, sessionId: string): SessionApi {
  const jsonHeaders = { 'content-type': 'application/json' }

  const api: SessionApi = {
    async createSession() {
      try {
        const res = await fetch(`${baseUrl}/session/create`, { method: 'POST' })
        if (!res.ok) return null
        const data = (await res.json()) as { session_id?: string }
        return data.session_id ?? null
      } catch {
        return null
      }
    },

    async sendMessage(message: string) {
      try {
        const res = await fetch(`${baseUrl}/session/${encodeURIComponent(sessionId)}/message`, {
          method: 'POST',
          headers: jsonHeaders,
          body: JSON.stringify({ message }),
        })
        return res.ok
      } catch {
        return false
      }
    },

    async abort() {
      try {
        await fetch(`${baseUrl}/session/${encodeURIComponent(sessionId)}/abort`, {
          method: 'POST',
        })
      } catch {
        // ignore
      }
    },

    streamEvents(onEvent, onClose) {
      void (async () => {
        try {
          const res = await fetch(`${baseUrl}/session/${encodeURIComponent(sessionId)}/events`)
          if (!res.ok || !res.body) {
            onClose()
            return
          }
          const reader = res.body.getReader()
          const decoder = new TextDecoder()
          let buffer = ''

          for (;;) {
            const { done, value } = await reader.read()
            if (done) break
            buffer += decoder.decode(value, { stream: true })
            const lines = buffer.split('\n')
            buffer = lines.pop() ?? ''
            for (const line of lines) {
              if (line.startsWith('data: ')) {
                try {
                  onEvent(JSON.parse(line.slice(6)) as SessionEvent)
                } catch {
                  // ignore malformed
                }
              }
            }
          }
        } catch {
          // connection lost
        }
        onClose()
      })()
    },

    close() {
      // fetch streams are closed by aborting reader; best-effort noop here
    },
  }

  return api
}
