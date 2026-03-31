import { defineStore } from 'pinia'
import { ref } from 'vue'

export interface Message {
  role: 'user' | 'assistant'
  content: string
  voucher?: Record<string, unknown> | null
  confirmed?: boolean
  time?: string
}

export interface SessionSummary {
  session_id: string
  created_at: string
  last_active: string
  voucher_count: number
  message_count?: number
  title?: string
  preview?: string
  pinned?: boolean
  archived?: boolean
}

export interface SessionData {
  session_id: string
  created_at: string
  last_active: string
  messages: Message[]
  voucher_state: Record<string, unknown> | null
  metadata: Record<string, unknown>
}

export const useSessionStore = defineStore('session', () => {
  const currentSessionId = ref<string>('')
  const messages = ref<Message[]>([])
  const sessions = ref<SessionSummary[]>([])
  const loading = ref(false)
  const sessionSearchKeyword = ref('')
  const includeArchived = ref(false)

  async function fetchSessions(search = sessionSearchKeyword.value, includeArchivedFlag = includeArchived.value) {
    sessionSearchKeyword.value = search
    includeArchived.value = includeArchivedFlag
    const params = new URLSearchParams()
    if (search.trim()) params.set('search', search.trim())
    if (includeArchivedFlag) params.set('include_archived', 'true')
    const query = params.toString()
    const res = await fetch(`/sessions${query ? `?${query}` : ''}`)
    if (res.ok) {
      sessions.value = await res.json()
    }
  }

  async function loadSession(sessionId: string) {
    loading.value = true
    try {
      const res = await fetch(`/sessions/${sessionId}`)
      if (res.ok) {
        const data: SessionData = await res.json()
        currentSessionId.value = data.session_id
        messages.value = data.messages
      }
    } finally {
      loading.value = false
    }
  }

  async function restoreLatest() {
    await fetchSessions()
    if (sessions.value.length > 0) {
      await loadSession(sessions.value[0].session_id)
    } else {
      await newSession()
      messages.value = []
    }
  }

  async function deleteSession(sessionId: string) {
    const res = await fetch(`/agent/session/${sessionId}`, { method: 'DELETE' })
    if (res.ok) {
      await fetchSessions()
      if (currentSessionId.value === sessionId) {
        currentSessionId.value = ''
        messages.value = []
      }
    }
  }

  async function updateSession(sessionId: string, patch: Record<string, unknown>) {
    const res = await fetch(`/sessions/${sessionId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(patch),
    })
    if (res.ok) {
      await fetchSessions()
    }
  }

  async function newSession(title = '') {
    const candidateId = crypto.randomUUID()
    const res = await fetch('/sessions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        session_id: candidateId,
        title,
      }),
    })

    if (res.ok) {
      const data: SessionData = await res.json()
      currentSessionId.value = data.session_id
      messages.value = []
      await fetchSessions()
      return
    }

    // fallback if backend create fails
    currentSessionId.value = candidateId
    messages.value = []
  }

  return {
    currentSessionId,
    messages,
    sessions,
    loading,
    sessionSearchKeyword,
    includeArchived,
    fetchSessions,
    loadSession,
    restoreLatest,
    deleteSession,
    updateSession,
    newSession,
  }
})
