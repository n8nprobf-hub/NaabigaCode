export type SessionEvent =
  | { type: 'user'; text: string }
  | { type: 'assistant'; text: string }
  | { type: 'tool'; name: string; input?: unknown; output?: unknown }
  | { type: 'thinking'; text?: string }
  | { type: 'error'; message: string }
  | { type: 'done' }
  | { type: 'aborted' }
  | { type: 'info'; message: string }

export function useSessionEvents(sessionId: string | null) {
  // In a real app this would use EventSource or fetch with ReadableStream.
  // For this scaffold we expose the event stream contract only.
  const connect = () => {
    if (!sessionId) return null
    const url = `http://localhost:8400/session/${encodeURIComponent(sessionId)}/events`
    const es = new EventSource(url)
    return es
  }

  const sendMessage = async (sessionId: string, message: string) => {
    const res = await fetch(`http://localhost:8400/session/${encodeURIComponent(sessionId)}/message`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ message }),
    })
    return res.ok
  }

  const createSession = async () => {
    const res = await fetch('http://localhost:8400/session/create', { method: 'POST' })
    if (!res.ok) return null
    const data = await res.json()
    return data.session_id as string
  }

  const abort = async (sessionId: string) => {
    await fetch(`http://localhost:8400/session/${encodeURIComponent(sessionId)}/abort`, {
      method: 'POST',
    })
  }

  return { connect, sendMessage, createSession, abort }
}
