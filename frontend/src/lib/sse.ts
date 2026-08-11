import { useEffect } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { getToken } from './api.ts'

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? '/api/v1'

const EVENT_TO_KEYS: Array<[RegExp, string[]]> = [
  [/^inventory\./, ['inventory', 'products', 'dashboard']],
  [/^orders\./, ['orders', 'products', 'dashboard', 'health']],
  [/^price\./, ['prices', 'products']],
  [/^market\./, ['market', 'products']],
  [/^health\./, ['health', 'products', 'dashboard']],
  [/^catalog\./, ['products']],
  [/^purchasing\./, ['purchasing', 'products']],
  [/^equipment\./, ['equipment']],
  [/^knowledge\./, ['knowledge']],
]

export function useEventStream() {
  const queryClient = useQueryClient()

  useEffect(() => {
    const token = getToken()
    if (!token) return
    let cursor = 0
    let closed = false
    let retry: number | undefined

    async function connect() {
      try {
        const response = await fetch(
          `${API_BASE}/events/stream?after=${cursor}&limit=200`,
          { headers: { Authorization: `Bearer ${token}` } },
        )
        if (!response.ok || !response.body) return
        const reader = response.body.getReader()
        const decoder = new TextDecoder()
        let buffer = ''
        while (!closed) {
          const { done, value } = await reader.read()
          if (done) break
          buffer += decoder.decode(value, { stream: true })
          const events = buffer.split('\n\n')
          buffer = events.pop() ?? ''
          for (const chunk of events) {
            const line = chunk.split('\n').find((l) => l.startsWith('data: '))
            if (!line) continue
            try {
              const event = JSON.parse(line.slice(6))
              cursor = Math.max(cursor, event.sequence_id)
              for (const [pattern, keys] of EVENT_TO_KEYS) {
                if (pattern.test(event.event_type)) {
                  keys.forEach((key) =>
                    queryClient.invalidateQueries({ queryKey: [key] }),
                  )
                }
              }
            } catch {
              // ignore malformed frames
            }
          }
        }
      } catch {
        // connection dropped; retry below
      }
      if (!closed) retry = window.setTimeout(connect, 3000)
    }

    void connect()
    return () => {
      closed = true
      if (retry) window.clearTimeout(retry)
    }
  }, [queryClient])
}
