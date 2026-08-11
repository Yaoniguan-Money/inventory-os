import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { Send } from 'lucide-react'
import { api } from '../lib/api.ts'
import { Card, PageHeader } from '../components/ui.tsx'

interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
  citations?: Array<{ document_title: string; excerpt: string }>
}

export default function AssistantPage() {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [input, setInput] = useState('')

  const chat = useMutation({
    mutationFn: (query: string) =>
      api.post<{
        answer: string
        citations: Array<{ document_title: string; excerpt: string }>
        provider: string
        disclaimer: string
      }>('/ai/employee-assistant', { query }),
    onSuccess: (data) => {
      setMessages((m) => [
        ...m,
        { role: 'assistant', content: data.answer, citations: data.citations },
      ])
    },
  })

  function send() {
    const text = input.trim()
    if (!text) return
    setMessages((m) => [...m, { role: 'user', content: text }])
    setInput('')
    chat.mutate(text)
  }

  return (
    <div>
      <PageHeader
        title="员工助手"
        description="结合企业知识库与只读业务数据的内部问答（遵循调用者权限）"
      />
      <Card className="flex h-[70vh] flex-col">
        <div className="flex-1 space-y-3 overflow-y-auto pb-3">
          {messages.length === 0 && (
            <div className="py-10 text-center text-sm text-slate-500">
              试试问：“A001 还能卖多少？”或“设备 E-07 报错 302 先检查什么？”
            </div>
          )}
          {messages.map((m, i) => (
            <div
              key={i}
              className={`max-w-[85%] rounded-xl px-4 py-3 text-sm ${
                m.role === 'user'
                  ? 'ml-auto bg-sky-600/20 text-sky-200'
                  : 'border border-slate-800 bg-slate-900/70 text-slate-200'
              }`}
            >
              {m.content}
              {m.citations && m.citations.length > 0 && (
                <div className="mt-2 space-y-1 border-t border-slate-800 pt-2">
                  {m.citations.map((c, j) => (
                    <div key={j} className="text-xs text-slate-400">
                      <span className="text-sky-300">{c.document_title}</span>：{c.excerpt}
                    </div>
                  ))}
                </div>
              )}
            </div>
          ))}
          {chat.isPending && (
            <div className="text-sm text-slate-500">思考中…</div>
          )}
        </div>
        <div className="flex gap-2 border-t border-slate-800 pt-3">
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && send()}
            placeholder="向员工助手提问…"
            className="flex-1 rounded-lg border border-slate-700 bg-slate-800/70 px-3 py-2 text-sm outline-none focus:border-sky-500"
          />
          <button
            onClick={send}
            disabled={!input.trim() || chat.isPending}
            className="rounded-lg bg-sky-600 px-4 text-white hover:bg-sky-500 disabled:opacity-50"
          >
            <Send className="h-4 w-4" />
          </button>
        </div>
      </Card>
    </div>
  )
}
